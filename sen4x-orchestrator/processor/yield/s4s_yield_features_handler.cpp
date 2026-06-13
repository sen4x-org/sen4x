#include <QJsonDocument>
#include <QJsonObject>
#include <QRegularExpression>
#include <fstream>

#include "logger.hpp"
#include "processorhandlerhelper.h"
#include "s4s_yield_features_handler.hpp"
#include "processor/s4c_utils.hpp"
#include "stepexecutiondecorator.h"

#include "processor/products/generichighlevelproducthelper.h"
using namespace orchestrator::products;

// TODO: These defines shoule be extracted from config
static QStringList YIELD_INPUT_MARKER_NAMES = {"LAI"};

QList<std::reference_wrapper<TaskToSubmit>>
S4SYieldFeaturesHandler::CreateTasks(const S4SYieldJobConfig &cfg, QList<TaskToSubmit> &outAllTasksList,
                             const S4CMarkersDB1DataExtractStepsBuilder &dataExtrStepsBuilder)
{
    int curTaskIdx = 0;
    int yieldFeatExtrIdx = -1;
    int prdFormatterParentIdx = -1;
    const QList<MarkerType> &enabledMarkers = dataExtrStepsBuilder.GetEnabledMarkers();
    QList<int> mergeTasksIndexes;
    QList<std::reference_wrapper<const TaskToSubmit>> mergeTasks;
    for (const auto &marker: enabledMarkers) {
        // Create data extraction tasks if needed
        int minDataExtrIndex = curTaskIdx;
        dataExtrStepsBuilder.CreateTasks(marker, outAllTasksList, curTaskIdx);
        int maxDataExtrIndex = curTaskIdx-1;

        if (YIELD_INPUT_MARKER_NAMES.contains(marker.marker)) {
            // create the merging tasks if needed
            int mergeTaskIdx = CreateMergeTasks(outAllTasksList, marker.marker.toLower() + "-data-extraction-merge",
                                                    minDataExtrIndex, maxDataExtrIndex, curTaskIdx);
            mergeTasksIndexes.push_back(mergeTaskIdx);
            mergeTasks.append(outAllTasksList[mergeTaskIdx]);
        }
    }

    outAllTasksList.append(TaskToSubmit{"s4s-savitzky-golay", mergeTasks});
    int sgIdx = curTaskIdx++;

    outAllTasksList.append(TaskToSubmit{ "s4s-yield-parcels-extraction", {} });
    int extractParcelsIdx = curTaskIdx++;

    outAllTasksList.append(TaskToSubmit{ "s4s-extract-weather-features", {outAllTasksList[extractParcelsIdx]}  });
    int weatherFeatIdx = curTaskIdx++;
    outAllTasksList.append(TaskToSubmit{ "s4s-merge-weather-features", {outAllTasksList[weatherFeatIdx]}  });
    int mergeWeatherFeatIdx = curTaskIdx++;

    outAllTasksList.append(TaskToSubmit{ "s4s-merge-lai-with-grid", {outAllTasksList[weatherFeatIdx]}  });
    int mergeLaiGridIdx = curTaskIdx++;

    QList<std::reference_wrapper<const TaskToSubmit>> mergeAllFeatTasks = {outAllTasksList[sgIdx],
                                                                           outAllTasksList[mergeWeatherFeatIdx]};
    if (cfg.enableSafy) {
        outAllTasksList.append(TaskToSubmit{ "s4s-safy-lut", mergeTasks });
        int safyLutTaskIdx = curTaskIdx++;
        outAllTasksList.append(TaskToSubmit{ "s4s-safy-optim", {outAllTasksList[safyLutTaskIdx], outAllTasksList[mergeLaiGridIdx]} });
        int safyOptimIdx = curTaskIdx++;
        mergeAllFeatTasks.push_back(outAllTasksList[safyOptimIdx]);
    }

    if (cfg.historicalYieldFile.size() > 0 && cfg.suPath.size() > 0) {
        outAllTasksList.append(TaskToSubmit{ "s4s-yield-trend-features-extraction", {} });
        int trendFeatExtrIdx = curTaskIdx++;
        outAllTasksList.append(TaskToSubmit{ "s4s-yield-parcels-to-su", {} });
        int parcelIdToSUIdExtrIdx = curTaskIdx++;
        outAllTasksList.append(TaskToSubmit{ "s4s-yield-parcels-trend-extraction", {outAllTasksList[extractParcelsIdx],
                                             outAllTasksList[trendFeatExtrIdx], outAllTasksList[parcelIdToSUIdExtrIdx]} });
        int extractParcelTrendsIdx = curTaskIdx++;
        mergeAllFeatTasks.push_back(outAllTasksList[extractParcelTrendsIdx]);
    }

    outAllTasksList.append(TaskToSubmit{ "s4s-merge-all-features", mergeAllFeatTasks  });
    int mergeAllFeatIdx = curTaskIdx++;
    outAllTasksList.append(TaskToSubmit{ "s4s-yield-features-extraction", {outAllTasksList[mergeAllFeatIdx]} });

    yieldFeatExtrIdx = curTaskIdx++;
    prdFormatterParentIdx = yieldFeatExtrIdx;


    outAllTasksList.append(TaskToSubmit{ "yield-feat-product-formatter", {outAllTasksList[prdFormatterParentIdx]} });

    QList<std::reference_wrapper<TaskToSubmit>> allTasksListRef;
    for (TaskToSubmit &task : outAllTasksList) {
        allTasksListRef.append(task);
    }
    return allTasksListRef;
}

NewStepList S4SYieldFeaturesHandler::CreateSteps(QList<TaskToSubmit> &allTasksList,const S4SYieldJobConfig &cfg,
                                         const S4CMarkersDB1DataExtractStepsBuilder &dataExtrStepsBuilder)
{
    int curTaskIdx = 0;
    NewStepList allSteps;
    QStringList prdFormatterFiles;
    QString yieldFeaturesOutputPath;
    const QList<MarkerType> &enabledMarkers = dataExtrStepsBuilder.GetEnabledMarkers();
    // if only data extraction is needed, then we create the filter ids step into the general configured directory
    QString mdb1File;
    for (const auto &marker: enabledMarkers) {
        QStringList dataExtrDirs;
        // Create the data extraction steps if needed
        dataExtrStepsBuilder.CreateSteps(marker, allTasksList, allSteps, curTaskIdx, dataExtrDirs);

        if (YIELD_INPUT_MARKER_NAMES.contains(marker.marker)) {
            // If scheduled jobs, force adding the data extraction directories for all markers as data extraction source
            if (cfg.isScheduled) {
                // add a data extraction dir corresponding to the scheduled date which is saved as jobCfg.maxPrdDate
                const QString &dataExtrDirName = dataExtrStepsBuilder.GetDataExtractionDir(marker.marker);
                if (!dataExtrDirs.contains(dataExtrDirName)) {
                    QDir().mkpath(dataExtrDirName);
                    dataExtrDirs.append(dataExtrDirName);
                }
            }
            const QString &retMergedFile = CreateStepsForFilesMerge(cfg, dataExtrDirs, allSteps,
                                                                     allTasksList, curTaskIdx);
            mdb1File = retMergedFile;
        }
    }
    if (mdb1File.size() == 0) {
        cfg.pCtx->MarkJobFailed(cfg.event.jobId);
        throw std::runtime_error(
            QStringLiteral(
                "Impossible to create the merged markers file. LAI Marker not enabled in database for MDB1?")
                .toStdString());
    }

    TaskToSubmit &sgTask = allTasksList[curTaskIdx++];
    TaskToSubmit &parcelExtrTask = allTasksList[curTaskIdx++];

    TaskToSubmit &weatherFeatTask = allTasksList[curTaskIdx++];
    TaskToSubmit &weatherFeatMergeTask = allTasksList[curTaskIdx++];
    TaskToSubmit &mergeLaiGridTask = allTasksList[curTaskIdx++];
    int safyLutIdx = -1, safyOptimIdx = -1;
    if (cfg.enableSafy) {
        safyLutIdx = curTaskIdx++;
        safyOptimIdx = curTaskIdx++;
    }

    int trendFeatExtrIdx = -1, parcelsToSuExtrIdx = -1, parcelsTrendExtrIdx = -1;
    if (cfg.historicalYieldFile.size() > 0 && cfg.suPath.size() > 0) {
        trendFeatExtrIdx = curTaskIdx++;
        parcelsToSuExtrIdx = curTaskIdx++;
        parcelsTrendExtrIdx = curTaskIdx++;
    }

    TaskToSubmit &mergeAllFeatTask = allTasksList[curTaskIdx++];
    TaskToSubmit &yieldFeatTask = allTasksList[curTaskIdx++];

    // Resulting files from tasks
    const QString &sgLaiPath = sgTask.GetFilePath("sg_lai_outputs.csv");
    const QString &sgCropGrowthIndicesPath = sgTask.GetFilePath("sg_crop_growth_indices.csv");
    const QString &sgYieldLaiFeaturesPath = sgTask.GetFilePath("yield_lai_features.csv");

    const QString &parcelGpkgPath = parcelExtrTask.GetFilePath("parcels.gpkg");
    const QString &parcelFeaturesCsvPath = parcelExtrTask.GetFilePath("parcel_features.csv");

    const QString &weatherWorkingDirPath = weatherFeatTask.GetFilePath("");

    // Workaround: Althogh created by weather features task, we add these here in order to avoid putting them in the same directory
    const QString &outGridToParcelIdsPath = weatherFeatMergeTask.GetFilePath("grid_to_parcels.csv");
    const QString &outParcelIdsToGridPath = weatherFeatMergeTask.GetFilePath("parcels_to_grid.csv");
    const QString &outWeatherFeaturesPath = weatherFeatMergeTask.GetFilePath("weather_raw_features.csv");

    const QString &outMergedLaiGrid = mergeLaiGridTask.GetFilePath("lai_with_grid.csv");

    const QString &allFeatOutputPath = mergeAllFeatTask.GetFilePath("merged_weather_sg_features.csv");
    yieldFeaturesOutputPath = yieldFeatTask.GetFilePath("yield_features.csv");

    // we expect the value to be something like /mnt/archive/s4s_yield/{site}/{year}/SAFY_Config/safy_params.json
    const QString &safyParamFile = cfg.GetProcessorDirValue(cfg.parameters, cfg.configParameters, "safy_params_path",
                                                        cfg.siteShortName, cfg.season.name, QString::number(cfg.year));

    // Inputs extraction and reflectances stack tif creation
    const QStringList &sgArgs = GetSGLaiTaskArgs(cfg.year, mdb1File, sgLaiPath, sgCropGrowthIndicesPath, sgYieldLaiFeaturesPath);
    allSteps.append(CreateTaskStep(sgTask, "SavitzkyGolay", sgArgs ));

    const QStringList &parcelsExtractionArgs = GetParcelsExtractionTaskArgs(cfg.event.siteId, cfg.season.seasonId,
                                                                                  parcelGpkgPath, parcelFeaturesCsvPath);
    allSteps.append(CreateTaskStep(parcelExtrTask, "ParcelsExtraction", parcelsExtractionArgs));

    const QStringList &weatherFeaturesExtractionArgs = GetWeatherFeaturesTaskArgs(cfg.weatherPrdPaths, parcelGpkgPath,
                                                                                  weatherWorkingDirPath,
                                                                                  outGridToParcelIdsPath, outParcelIdsToGridPath);
    allSteps.append(CreateTaskStep(weatherFeatTask, "WeatherFeatures", weatherFeaturesExtractionArgs));

    const QStringList &weatherFeaturesMergeArgs = GetWeatherFeaturesMergeTaskArgs(weatherWorkingDirPath, outWeatherFeaturesPath);
    allSteps.append(CreateTaskStep(weatherFeatMergeTask, "WeatherFeaturesMerge", weatherFeaturesMergeArgs));

    const QStringList &mergeLaiGridArgs = GetMergeLaiGridTaskArgs(mdb1File, outParcelIdsToGridPath, outMergedLaiGrid);
    allSteps.append(CreateTaskStep(mergeLaiGridTask, "MergeLaiWitGrid", mergeLaiGridArgs));

    QString safyOptimOutputPath;
    if (cfg.enableSafy) {
        TaskToSubmit &safyLutTask = allTasksList[safyLutIdx];
        TaskToSubmit &safyOptimTask = allTasksList[safyOptimIdx];

        const QString &safyLutRangesFilesDirPath = safyLutTask.GetFilePath("");
        const QString &safyLutOutputDirPath = safyLutTask.GetFilePath("");

        const QString &safyOptimWorkingDirPath = safyOptimTask.GetFilePath("");
        safyOptimOutputPath = safyOptimTask.GetFilePath("safy_optim_features.csv");

        const QStringList &safyLutArgs = GetSafyLutTaskArgs(cfg.weatherPrdPaths, safyParamFile, safyLutRangesFilesDirPath, safyLutOutputDirPath);
        allSteps.append(CreateTaskStep(safyLutTask, "SafyLut", safyLutArgs));

        const QStringList &safyOptimArgs = GetSafyOptimTaskArgs(cfg.weatherPrdPaths, cfg.year, outMergedLaiGrid,
                                                                outGridToParcelIdsPath, safyParamFile, safyLutRangesFilesDirPath,
                                                                safyLutOutputDirPath, safyOptimWorkingDirPath, safyOptimOutputPath);
        allSteps.append(CreateTaskStep(safyOptimTask, "SafyOptim", safyOptimArgs));
    }

    QString parcelTrendFeaturesPath;
    if (cfg.historicalYieldFile.size() > 0 && cfg.suPath.size() > 0) {
        TaskToSubmit &trendFeatExtrTask = allTasksList[trendFeatExtrIdx];
        TaskToSubmit &parcelsToSUExtrTask = allTasksList[parcelsToSuExtrIdx];
        TaskToSubmit &parcelsTrendExtrTask = allTasksList[parcelsTrendExtrIdx];

        const QString &trendFeaturesPath = trendFeatExtrTask.GetFilePath("trend_features.csv");
        const QString &parcelToSUPath = parcelsToSUExtrTask.GetFilePath("parcel_to_su_mapping.csv");
        parcelTrendFeaturesPath = parcelsTrendExtrTask.GetFilePath("parcels_trend_features.csv");

        const QStringList &trendArgs = GetTrendFeaturesTaskArgs(cfg.historicalYieldFile, cfg.year, trendFeaturesPath);
        allSteps.append(CreateTaskStep(trendFeatExtrTask, "TrendFeatures", trendArgs ));

        const QStringList &parcelToSUArgs = GetParcelToSUTaskArgs(cfg.event.siteId, cfg.season.seasonId, cfg.suPath, parcelToSUPath);
        allSteps.append(CreateTaskStep(parcelsToSUExtrTask, "ParcelsToSU", parcelToSUArgs ));

        const QStringList &parcelTrendExtractionArgs = GetParcelTrendsTaskArgs(trendFeaturesPath, parcelFeaturesCsvPath, parcelToSUPath, parcelTrendFeaturesPath);
        allSteps.append(CreateTaskStep(parcelsTrendExtrTask, "ParcelTrendFeatures", parcelTrendExtractionArgs ));
    }

    const QStringList &allFeatureMergeArgs = GetAllFeaturesMergeTaskArgs(outWeatherFeaturesPath, sgCropGrowthIndicesPath, safyOptimOutputPath,
                                                                          allFeatOutputPath, sgYieldLaiFeaturesPath, parcelFeaturesCsvPath,
                                                                         parcelTrendFeaturesPath);
    allSteps.append(CreateTaskStep(mergeAllFeatTask, "AllFeaturesMerge", allFeatureMergeArgs));

    const QStringList &yieldFeatExtractionArgs = GetYieldFeaturesTaskArgs(allFeatOutputPath, yieldFeaturesOutputPath);
    allSteps.append(CreateTaskStep(yieldFeatTask, "YieldFeatures", yieldFeatExtractionArgs));
    prdFormatterFiles.append(yieldFeaturesOutputPath);

    TaskToSubmit &productFormatterTask = allTasksList[curTaskIdx++];

    const QStringList &productFormatterArgs = GetProductFormatterArgs(productFormatterTask, cfg, prdFormatterFiles);
    allSteps.append(CreateTaskStep(productFormatterTask, "ProductFormatter", productFormatterArgs));

    return allSteps;
}

int S4SYieldFeaturesHandler::CreateMergeTasks(QList<TaskToSubmit> &outAllTasksList, const QString &taskName,
                                        int minPrdDataExtrIndex, int maxPrdDataExtrIndex, int &curTaskIdx) {
    outAllTasksList.append(TaskToSubmit{ taskName, {} });
    int mergeTaskIdx = curTaskIdx++;
    // update the parents for this task
    if (minPrdDataExtrIndex != -1) {
        for (int i = minPrdDataExtrIndex; i <= maxPrdDataExtrIndex; i++) {
            outAllTasksList[mergeTaskIdx].parentTasks.append(outAllTasksList[i]);
        }
    }
    return mergeTaskIdx;
}

QString S4SYieldFeaturesHandler::CreateStepsForFilesMerge(const S4SYieldJobConfig &jobCfg,
                              const QStringList &dataExtrDirs, NewStepList &steps,
                              QList<TaskToSubmit> &allTasksList, int &curTaskIdx) {
    TaskToSubmit &mergeTask = allTasksList[curTaskIdx++];
    QString yearStr = QString::number(jobCfg.year);
    QString mergeResultFileName = yearStr.append("_LAI_Extracted_Data.csv");
    const QString &mergedFile = mergeTask.GetFilePath(mergeResultFileName);
    QStringList mergeArgs = { "Markers1CsvMerge", "-out", mergedFile, "-il" };
    mergeArgs += dataExtrDirs;
    steps.append(CreateTaskStep(mergeTask, "Markers1CsvMerge", mergeArgs));

    return mergedFile;
}

QStringList S4SYieldFeaturesHandler::GetSGLaiTaskArgs(int year, const QString &mdb1File, const QString &sgOutFile,
                                              const QString &outCropGrowthIndicesFile, const QString &outLaiMetricsFile)
{
    return {    "--input", mdb1File,
                "--year", QString::number(year),
                "--sg-output", sgOutFile,
                "--indices-output", outCropGrowthIndicesFile,
                "--metrics-output", outLaiMetricsFile
    };
}

QStringList S4SYieldFeaturesHandler::GetParcelsExtractionTaskArgs(int siteId, int seasonId, const QString &outFile, const QString &parcelFeaturesCsv)
{
    return { "-s", QString::number(siteId), "--season-id", QString::number(seasonId),
                "-o", outFile, "--parcel-features-csv", parcelFeaturesCsv};
}

QStringList S4SYieldFeaturesHandler::GetTrendFeaturesTaskArgs(const QString &input, int year, const QString &output)
{
    QStringList args = {
        "--input", input,
        "--output", output,
        "--year", QString::number(year)
    };
    return args;
}

QStringList S4SYieldFeaturesHandler::GetParcelToSUTaskArgs(int siteId, int seasonId, const QString &suPathFile, const QString &output)
{
    QStringList args = {
        "--site-id", QString::number(siteId),
        "--season-id", QString::number(seasonId),
        "--su-path", suPathFile,
        "--output", output,
        "--su-unique-id", "ID_2"        // TODO : this should be configurable
    };
    return args;
}

QStringList S4SYieldFeaturesHandler::GetParcelTrendsTaskArgs(const QString &trendFeaturesPath, const QString &parcelInfosFile, const QString &parcelToSUFile, const QString &output)
{
    QStringList args = {
        "--trend-features-list-file", trendFeaturesPath,
        "--parcels-info", parcelInfosFile,
        "--parcels-to-su", parcelToSUFile,
        "--output", output
    };
    return args;
}

QStringList S4SYieldFeaturesHandler::GetWeatherFeaturesTaskArgs(const QStringList &weatherFiles, const QString &parcelsShp,
                                                        const QString &outDir, const QString &outGridToParcels,
                                                        const QString &outParcelToGrid)
{
    QStringList args = { "-v", parcelsShp, "-o", outDir,
                        "-p", outParcelToGrid, "-g", outGridToParcels};
    args += "-i";
    args.append(weatherFiles);

    return args;
}

QStringList S4SYieldFeaturesHandler::GetWeatherFeaturesMergeTaskArgs(const QString &inDir, const QString &outWeatherFeatures)
{
    return { "Markers1CsvMerge", "-out", outWeatherFeatures, "-il", inDir };
}

QStringList S4SYieldFeaturesHandler::GetSafyLutTaskArgs(const QStringList &weatherFiles, const QString &safyParamFile,
                                                const QString &safyParamsRangesDir, const QString &outLutDir)
{
    QStringList args = { "-p", safyParamFile,
                "-r", safyParamsRangesDir,
                "-o", outLutDir};

    args += "-i";
    args.append(weatherFiles);

    return args;
}

QStringList S4SYieldFeaturesHandler::GetMergeLaiGridTaskArgs(const QString &inputLaiFile, const QString &parcelsToGridFile, const QString &outMergedFile)
{
    return { "Markers1CsvMerge", "-il", inputLaiFile, parcelsToGridFile, "-out", outMergedFile, "-ignnodatecol", "0"};
}

QStringList S4SYieldFeaturesHandler::GetSafyOptimTaskArgs(const QStringList &weatherFiles, int year, const QString &mergedLaiGrid,
                                                  const QString &gridToParcelsFile, const QString &safyParamsFile,
                                                  const QString &safyParamsRangesFile, const QString &lutDir,
                                                  const QString &workingDir, const QString &outSafyOptimFile)
{
    QStringList args = {    "-y", QString::number(year),
                "-a", mergedLaiGrid,
                "-g", gridToParcelsFile,
                "-p", safyParamsFile,
                "-r", safyParamsRangesFile,
                "-l", lutDir,
                "-w", workingDir,
                "-o", outSafyOptimFile};
    args += "-i";
    args.append(weatherFiles);

    return args;
}

QStringList S4SYieldFeaturesHandler::GetAllFeaturesMergeTaskArgs(const QString &weatherFeatFile, const QString &sgCropGrowthIndicesFile,
                                                      const QString &safyFeatsFile, const QString &outMergedFeatures,
                                                         const QString &sgYieldLaiFeaturesPath, const QString &parcelFeaturesCsv,
                                                                 const QString &parcelTrendFeaturesPath)
{
    QStringList args = { "Markers1CsvMerge",
             "-il", weatherFeatFile, sgCropGrowthIndicesFile, sgYieldLaiFeaturesPath, parcelFeaturesCsv};

    if (parcelTrendFeaturesPath.size() > 0) {
        args += parcelTrendFeaturesPath;
    }
    if(safyFeatsFile.size() > 0) {
        args += safyFeatsFile;
    }

    args.append({"-out", outMergedFeatures, "-ignnodatecol", "0"});

    return args;
}

QStringList S4SYieldFeaturesHandler::GetYieldFeaturesTaskArgs(const QString &inMergedFeatures, const QString &outYieldFeatures)
{

    return { "-i", inMergedFeatures, "-o", outYieldFeatures};
}

void S4SYieldFeaturesHandler::HandleJobSubmittedImpl(EventProcessingContext &ctx,
                                                const JobSubmittedEvent &event)
{
    S4SYieldJobConfig cfg(&ctx, event, processorDescr.shortName);
    S4CMarkersDB1DataExtractStepsBuilder dataExtrStepsBuilder;
    dataExtrStepsBuilder.Initialize(processorDescr.shortName, ctx, cfg.parameters, event.siteId, event.jobId, {"LAI"});

    QList<TaskToSubmit> allTasksList;
    QList<std::reference_wrapper<TaskToSubmit>> allTasksListRef = CreateTasks(cfg, allTasksList, dataExtrStepsBuilder);
    SubmitTasks(ctx, cfg.event.jobId, allTasksListRef);
    NewStepList allSteps = CreateSteps(allTasksList, cfg, dataExtrStepsBuilder);
    ctx.SubmitSteps(allSteps);
}

void S4SYieldFeaturesHandler::HandleTaskFinishedImpl(EventProcessingContext &ctx,
                                                const TaskFinishedEvent &event)
{
    if (event.module == "yield-feat-product-formatter") {
        const QString &prodName = GetOutputProductName(ctx, event);
        const QString &productFolder =
            GetFinalProductFolder(ctx, event.jobId, event.siteId) + "/" + prodName;
        if (prodName != "") {
            const QString &quicklook = GetProductFormatterQuicklook(ctx, event);
            const QString &footPrint = GetProductFormatterFootprint(ctx, event);
            // Insert the product into the database
            GenericHighLevelProductHelper prdHelper(productFolder);
            int prdId = ctx.InsertProduct({ ProductType::S4SYieldFeatProductTypeId, event.processorId,
                                            event.siteId, event.jobId, productFolder, prdHelper.GetAcqDate(),
                                            prodName, quicklook, footPrint,
                                            std::experimental::nullopt, TileIdList(), ProductIdsList() });
            const QString &prodFolderOutPath =
                ctx.GetOutputPath(event.jobId, event.taskId, event.module,
                                  processorDescr.shortName) +
                "/" + "prd_infos.txt";

            QFile file(prodFolderOutPath);
            if (file.open(QIODevice::ReadWrite)) {
                QTextStream stream(&file);
                stream << prdId << ';' << productFolder << '\n';
            }
            ctx.MarkJobFinished(event.jobId);
            // Now remove the job folder containing temporary files
            // TODO: check why it still remove the folder even if the key is set to 1
            RemoveJobFolder(ctx, event.jobId, processorDescr.shortName);
        } else {
            ctx.MarkJobFailed(event.jobId);
            Logger::error(
                QStringLiteral("Cannot insert into database the product with name %1 and folder %2")
                    .arg(prodName)
                    .arg(productFolder));
        }
    }
}

ProcessorJobDefinitionParams S4SYieldFeaturesHandler::GetProcessingDefinitionImpl(
    SchedulingContext &ctx,
    int siteId,
    int scheduledDate,
    const ConfigurationParameterValueMap &requestOverrideCfgValues)
{
    ProcessorJobDefinitionParams params;

    QDateTime seasonStartDate;
    QDateTime seasonEndDate;
    // extract the scheduled date
    QDateTime qScheduledDate = QDateTime::fromTime_t(scheduledDate);
    bool success = GetSeasonStartEndDates(ctx, siteId, seasonStartDate, seasonEndDate,
                                          qScheduledDate, requestOverrideCfgValues);
    // if cannot get the season dates
    if (!success) {
        Logger::debug(QStringLiteral("Scheduler Yield Features: Error getting season start dates for "
                                     "site %1 for scheduled date %2!")
                          .arg(siteId)
                          .arg(qScheduledDate.toString()));
        return params;
    }

    QDateTime limitDate = seasonEndDate.addMonths(2);
    if (qScheduledDate > limitDate) {
        Logger::debug(QStringLiteral("Scheduler Yield Features: Error scheduled date %1 greater than the "
                                     "limit date %2 for site %3!")
                          .arg(qScheduledDate.toString())
                          .arg(limitDate.toString())
                          .arg(siteId));
        return params;
    }

    ConfigurationParameterValueMap cfgValues =
        ctx.GetConfigurationParameters(S4S_YIELD_FEAT_CFG_PREFIX, siteId, requestOverrideCfgValues);
    // we might have an offset in days from starting the downloading products to start the S4C L4A
    // production
    int startSeasonOffset = cfgValues[QStringLiteral(S4S_YIELD_FEAT_CFG_PREFIX) + "start_season_offset"].value.toInt();
    seasonStartDate = seasonStartDate.addDays(startSeasonOffset);

    QDateTime startDate = seasonStartDate;
    QDateTime endDate = qScheduledDate;
    // do not pass anymore the product list but the dates
    params.jsonParameters.append("{ \"scheduled_job\": \"1\", \"start_date\": \"" + startDate.toString("yyyyMMdd") + "\", " +
                                 "\"end_date\": \"" + endDate.toString("yyyyMMdd") + "\", " +
                                 "\"season_start_date\": \"" + seasonStartDate.toString("yyyyMMdd") + "\", " +
                                 "\"season_end_date\": \"" + seasonEndDate.toString("yyyyMMdd") + "\"}");

    // Normally, we need at least 1 product available, the crop mask and the shapefile in order to
    // be able to create a S4S Yield product but if we do not return here, the schedule block waiting
    // for products (that might never happen)
    bool waitForAvailProcInputs =
        (cfgValues[QStringLiteral(S4S_YIELD_FEAT_CFG_PREFIX) + "sched_wait_proc_inputs"].value.toInt() != 0);
    if ((waitForAvailProcInputs == false) || ((params.productList.size() > 0))) {
        params.isValid = true;
        Logger::debug(
            QStringLiteral("Executing scheduled job. Scheduler extracted for S4C L4A a number "
                           "of %1 products for site ID %2 with start date %3 and end date %4!")
                .arg(params.productList.size())
                .arg(siteId)
                .arg(startDate.toString())
                .arg(endDate.toString()));
    } else {
        Logger::debug(QStringLiteral("Scheduled job for S4S Yield and site ID %1 with start date %2 "
                                     "and end date %3 will not be executed "
                                     "(productsNo = %4)!")
                          .arg(siteId)
                          .arg(startDate.toString())
                          .arg(endDate.toString())
                          .arg(params.productList.size()));
    }

    return params;
}

QString S4SYieldFeaturesHandler::S4SYieldJobConfig::GetProcessorDirValue(const QJsonObject &parameters, const std::map<QString, QString> &configParameters,
                                                    const QString &key, const QString &siteShortName, const QString &seasonName, const QString &year,
                                                    const QString &defVal ) const {
    QString dataExtrDirName = ProcessorHandlerHelper::GetStringConfigValue(parameters, configParameters, key, S4S_YIELD_FEAT_CFG_PREFIX);

    if (dataExtrDirName.size() == 0) {
        dataExtrDirName = defVal;
    }
    dataExtrDirName = dataExtrDirName.replace("{site}", siteShortName);
    dataExtrDirName = dataExtrDirName.replace("{year}", year);
    dataExtrDirName = dataExtrDirName.replace("{season}", seasonName);
    dataExtrDirName = dataExtrDirName.replace("{processor}", procShortName);

    return dataExtrDirName;
}

QStringList S4SYieldFeaturesHandler::GetProductFormatterArgs(TaskToSubmit &productFormatterTask,
                                                     const S4SYieldJobConfig &cfg, const QStringList &listFiles) {
    QString strTimePeriod = cfg.startDate.toString("yyyyMMddTHHmmss").append("_").append(cfg.endDate.toString("yyyyMMddTHHmmss"));
    QStringList additionalArgs = {"-processor.generic.files"};
    additionalArgs += listFiles;
    return GetDefaultProductFormatterArgs(*(cfg.pCtx), productFormatterTask, cfg.event.jobId, cfg.event.siteId, "S4SYIELDFEAT", strTimePeriod,
                                         "generic", additionalArgs, true);
}

