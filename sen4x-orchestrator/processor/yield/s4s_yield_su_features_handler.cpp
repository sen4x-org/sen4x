#include <QJsonDocument>
#include <QJsonObject>
#include <QRegularExpression>
#include <fstream>

#include "logger.hpp"
#include "processorhandlerhelper.h"
#include "s4s_yield_su_features_handler.hpp"
#include "processor/s4c_utils.hpp"
#include "stepexecutiondecorator.h"

#include "processor/products/generichighlevelproducthelper.h"
using namespace orchestrator::products;

// TODO: These defines shoule be extracted from config
static QStringList YIELD_INPUT_MARKER_NAMES = {"LAI"};

QList<std::reference_wrapper<TaskToSubmit>>
S4SYieldSUFeaturesHandler::CreateTasks(const S4SYieldJobConfig &cfg, QList<TaskToSubmit> &outAllTasksList,
                             const S4CMarkersDB1DataExtractStepsBuilder &dataExtrStepsBuilder)
{
    int curTaskIdx = 0;
    QList<int> dataExtrParentTaskIdxs;
    for (int year: cfg.years) {
        outAllTasksList.append(TaskToSubmit{ "s4s-yield-esu-extraction", {} });
        int extractESUIdx = curTaskIdx++;
        dataExtrParentTaskIdxs.append(extractESUIdx);
    }
//    outAllTasksList.append(TaskToSubmit{ "s4s-yield-esu-extraction", {} });
//    int extractESUIdx = curTaskIdx++;
//    auto dataExtrParentTaskIdxs = {extractESUIdx};

    const QList<MarkerType> &enabledMarkers = dataExtrStepsBuilder.GetEnabledMarkers();
    QList<int> mergeTasksIndexes;
    QList<std::reference_wrapper<const TaskToSubmit>> mergeTasks;
    for (const auto &marker: enabledMarkers) {
        // Create data extraction tasks if needed
        int minDataExtrIndex = curTaskIdx;
        dataExtrStepsBuilder.CreateTasks(marker, outAllTasksList, curTaskIdx, dataExtrParentTaskIdxs);
        int maxDataExtrIndex = curTaskIdx-1;

        if (YIELD_INPUT_MARKER_NAMES.contains(marker.marker)) {
            // create the merging tasks if needed
            int mergeTaskIdx = CreateMergeTasks(outAllTasksList, marker.marker.toLower() + "-data-extraction-merge",
                                                    minDataExtrIndex, maxDataExtrIndex, curTaskIdx);
            mergeTasksIndexes.push_back(mergeTaskIdx);
            mergeTasks.append(outAllTasksList[mergeTaskIdx]);
        }
    }

    outAllTasksList.append(TaskToSubmit{ "s4s-yield-esu-aggregate", mergeTasks });
    int aggESUIdx = curTaskIdx++;

    outAllTasksList.append(TaskToSubmit{"s4s-savitzky-golay-wrp", {outAllTasksList[aggESUIdx]}  });
    int sgIdx = curTaskIdx++;

    outAllTasksList.append(TaskToSubmit{ "s4s-yield-trend-features-extraction", {} });
    int trendFeatExtrIdx = curTaskIdx++;
    outAllTasksList.append(TaskToSubmit{ "s4s-extract-weather-features", {}  });
    int weatherFeatIdx = curTaskIdx++;
    outAllTasksList.append(TaskToSubmit{ "s4s-merge-weather-features", {outAllTasksList[weatherFeatIdx]}  });
    int mergeWeatherFeatIdx = curTaskIdx++;
    outAllTasksList.append(TaskToSubmit{ "s4s-merge-all-features-wrp", {outAllTasksList[sgIdx],
                                                                        outAllTasksList[mergeWeatherFeatIdx],
                                                                        outAllTasksList[trendFeatExtrIdx]}  });
    int mergeAllFeatIdx = curTaskIdx++;
    outAllTasksList.append(TaskToSubmit{ "s4s-yield-features-extraction-wrp", {outAllTasksList[mergeAllFeatIdx]} });
    int yieldFeatExtrIdx = curTaskIdx++;
    outAllTasksList.append(TaskToSubmit{ "s4s-yield-su-merge-yearly-features", {outAllTasksList[yieldFeatExtrIdx]} });
    int mergeYearlyFeatIdx = curTaskIdx++;
    outAllTasksList.append(TaskToSubmit{ "yield-su-feat-product-formatter", {outAllTasksList[mergeYearlyFeatIdx] } });

    QList<std::reference_wrapper<TaskToSubmit>> allTasksListRef;
    for (TaskToSubmit &task : outAllTasksList) {
        allTasksListRef.append(task);
    }
    return allTasksListRef;
}

NewStepList S4SYieldSUFeaturesHandler::CreateSteps(QList<TaskToSubmit> &allTasksList,const S4SYieldJobConfig &cfg,
                                         const S4CMarkersDB1DataExtractStepsBuilder &dataExtrStepsBuilder)
{
    int curTaskIdx = 0;
    NewStepList allSteps;
    QStringList prdFormatterFiles;
    QStringList esuCSVPaths;
    QString suAdditionlInfoCSVPath;
    QList<int> ctYears;
    // create the step for ESU extraction
    for (const Product &ctPrd: cfg.cropTypePrds) {
        const QString &ctPath = ctPrd.fullPath;
        int ctYear = ctPrd.created.date().year();

        TaskToSubmit &esuExtrTask = allTasksList[curTaskIdx++];

        const QString &esuExtrPath = esuExtrTask.GetFilePath("");
        const QString &esuPath = esuExtrTask.GetFilePath("ESU_" + QString::number(ctYear) + ".csv");
        const QString &suAdditionlInfoPath = esuExtrTask.GetFilePath("SU_additional_info.csv");

        const QStringList &esuExtrArgs = GetEsuExtractionTaskArgs(cfg, esuExtrPath, esuPath, suAdditionlInfoPath,
                                                                  ctPath, ctYear);
        allSteps.append(CreateTaskStep(esuExtrTask, "ESUExtraction", esuExtrArgs ));

        esuCSVPaths.append(esuPath);
        ctYears.append(ctYear);
        suAdditionlInfoCSVPath = suAdditionlInfoPath;
    }

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
                "Yield SU: Impossible to create the merged markers file. LAI Marker not enabled in database for MDB1?")
                .toStdString());
    }

    TaskToSubmit &esuAggregateTask = allTasksList[curTaskIdx++];
    TaskToSubmit &sgTask = allTasksList[curTaskIdx++];
    TaskToSubmit &trendFeatExtrTask = allTasksList[curTaskIdx++];
    TaskToSubmit &weatherFeatTask = allTasksList[curTaskIdx++];
    TaskToSubmit &weatherFeatMergeTask = allTasksList[curTaskIdx++];
    TaskToSubmit &mergeAllFeatTask = allTasksList[curTaskIdx++];
    TaskToSubmit &yieldFeatTask = allTasksList[curTaskIdx++];
    TaskToSubmit &mergeYearlyYieldFeatTask = allTasksList[curTaskIdx++];

    // Resulting files from tasks
    const QString &esuAggWorkPath = esuAggregateTask.GetFilePath("");
    const QString &esuAggResultPath = esuAggregateTask.GetFilePath("LAIGrouped.csv");
    const QString &sgLaiPath = sgTask.GetFilePath("sg_lai_outputs.csv");
    const QString &trendFeaturesPath = trendFeatExtrTask.GetFilePath("trend_features.csv");
    const QString &sgCropGrowthIndicesPath = sgTask.GetFilePath("sg_crop_growth_indices.csv");
    const QString &sgYieldLaiFeaturesPath = sgTask.GetFilePath("yield_lai_features.csv");
    const QString &weatherWorkingDirPath = weatherFeatTask.GetFilePath("");
    // Workaround: Althogh created by weather featurs task, we add these here in order to avoid putting them in the same directory
    const QString &outWeatherFeaturesPath = weatherFeatMergeTask.GetFilePath("weather_raw_features.csv");
    const QString &allFeatOutputPath = mergeAllFeatTask.GetFilePath("merged_weather_sg_features.csv");
    const QString &yieldFeaturesOutputPath = yieldFeatTask.GetFilePath("yield_features.csv");
    const QString &yieldFeaturesPrevYearsOutputPath = yieldFeatTask.GetFilePath("yield_features_prev_years.csv");
    const QString &mergePrevYearsYieldFeatOutPath = mergeYearlyYieldFeatTask.GetFilePath("merged_prev_years_yield_features.csv");

    // Inputs extraction and reflectances stack tif creation
    const QStringList &esuAggArgs = GetESUAggregationTaskArgs(esuCSVPaths,ctYears,  mdb1File, esuAggWorkPath, esuAggResultPath);
    allSteps.append(CreateTaskStep(esuAggregateTask, "ESUAggregation", esuAggArgs ));

    // Inputs extraction and reflectances stack tif creation
    const QStringList &sgArgs = GetSGLaiTaskArgs(cfg.years, esuAggResultPath, sgLaiPath, sgCropGrowthIndicesPath, sgYieldLaiFeaturesPath);
    allSteps.append(CreateTaskStep(sgTask, "SavitzkyGolay", sgArgs ));

    const QStringList &trendArgs = GetTrendFeaturesTaskArgs(cfg.historicalYieldFile, cfg.years, trendFeaturesPath);
    allSteps.append(CreateTaskStep(trendFeatExtrTask, "TrendFeatures", trendArgs ));

    const QStringList &weatherFeaturesExtractionArgs = GetWeatherFeaturesTaskArgs(cfg.weatherPrdPaths, cfg.suPath, cfg.suUniqueId,
                                                                                  weatherWorkingDirPath);
    allSteps.append(CreateTaskStep(weatherFeatTask, "WeatherFeatures", weatherFeaturesExtractionArgs));

    const QStringList &weatherFeaturesMergeArgs = GetWeatherFeaturesMergeTaskArgs(weatherWorkingDirPath, outWeatherFeaturesPath);
    allSteps.append(CreateTaskStep(weatherFeatMergeTask, "WeatherFeaturesMerge", weatherFeaturesMergeArgs));

    const QStringList &allFeatureMergeArgs = GetAllFeaturesMergeTaskArgs(sgCropGrowthIndicesPath, trendFeaturesPath, outWeatherFeaturesPath, allFeatOutputPath,
                                                                         sgYieldLaiFeaturesPath, suAdditionlInfoCSVPath);
    allSteps.append(CreateTaskStep(mergeAllFeatTask, "AllFeaturesMerge", allFeatureMergeArgs));

    const QString &yieldFeatDirOutputPath = yieldFeatTask.GetFilePath("");
    const QStringList &yieldFeatExtractionArgs = GetYieldFeaturesTaskArgs(allFeatOutputPath, cfg.years.back(), yieldFeaturesOutputPath, yieldFeaturesPrevYearsOutputPath);
    allSteps.append(CreateTaskStep(yieldFeatTask, "YieldFeatures", yieldFeatExtractionArgs));

    const QString &mergedFeatDirOutputPath = mergeYearlyYieldFeatTask.GetFilePath("");
    const QStringList &mergeYieldFeaturesArgs = GetMergeYieldFeaturesTaskArgs(yieldFeaturesPrevYearsOutputPath, mergePrevYearsYieldFeatOutPath);
    allSteps.append(CreateTaskStep(mergeYearlyYieldFeatTask, "MergeYieldFeatures", mergeYieldFeaturesArgs));

    // we append the full directory containing all resulted files
    prdFormatterFiles.append(yieldFeatDirOutputPath);
    prdFormatterFiles.append(mergedFeatDirOutputPath);

    TaskToSubmit &productFormatterTask = allTasksList[curTaskIdx++];

    const QStringList &productFormatterArgs = GetProductFormatterArgs(productFormatterTask, cfg, prdFormatterFiles);
    allSteps.append(CreateTaskStep(productFormatterTask, "ProductFormatter", productFormatterArgs));

    return allSteps;
}

int S4SYieldSUFeaturesHandler::CreateMergeTasks(QList<TaskToSubmit> &outAllTasksList, const QString &taskName,
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

QString S4SYieldSUFeaturesHandler::CreateStepsForFilesMerge(const S4SYieldJobConfig &jobCfg,
                              const QStringList &dataExtrDirs, NewStepList &steps,
                              QList<TaskToSubmit> &allTasksList, int &curTaskIdx) {
    TaskToSubmit &mergeTask = allTasksList[curTaskIdx++];
    QString yearStr = QString::number(jobCfg.years.back());
    QString mergeResultFileName = yearStr.append("_LAI_Extracted_Data.csv");
    const QString &mergedFile = mergeTask.GetFilePath(mergeResultFileName);
    QStringList mergeArgs = { "Markers1CsvMerge", "-out", mergedFile, "-il" };
    mergeArgs += dataExtrDirs;
    steps.append(CreateTaskStep(mergeTask, "Markers1CsvMerge", mergeArgs));

    return mergedFile;
}

QStringList S4SYieldSUFeaturesHandler::GetEsuExtractionTaskArgs(const S4SYieldJobConfig &cfg, const QString &workingDir,
                                                                const QString &outESUCsvFile,  const QString &outSUAdditionalInfoCsvFile,
                                                                const QString &ctPath, int ctYear)
{
    QStringList args = {    "--crop-type-path", ctPath,
                "--crop-type-year", QString::number(ctYear),
                "--su-path", cfg.suPath,
                "--su-unique-id", cfg.suUniqueId,
                "--working-dir", workingDir,
                "--output", outESUCsvFile,
                "--out-additional-su-info", outSUAdditionalInfoCsvFile
    };
    args += "--out-tile-rasters";
    for (const Tile &tile: cfg.siteTiles) {
        const QMap<QString, QString> &esuRasters = cfg.esuRasterPaths[ctYear];
        args += esuRasters[tile.tileId];
    }
    args += "--tiles";
    for(const Tile &tile: cfg.siteTiles) {
        args += tile.tileId;
    }

    return args;
}

QStringList S4SYieldSUFeaturesHandler::GetESUAggregationTaskArgs(const QStringList &esuCsvFiles, const QList<int> &ctYears,
                                                                 const QString &laiMergedPath, const QString &workingDir,
                                                                 const QString &outAggregatedLAI)
{
    QStringList args = {
                "--lai-merged-path", laiMergedPath,
                "--working-dir", workingDir,
                "--output", outAggregatedLAI
    };

    args += "--esu-path";
    for (const QString &esuFile: esuCsvFiles) {
        args += esuFile;
    }
    args += "--years";
    for (int year: ctYears) {
        args += QString::number(year);
    }
    return args;
}

QStringList S4SYieldSUFeaturesHandler::GetSGLaiTaskArgs(const std::vector<int> &years, const QString &mdb1File, const QString &sgOutFile,
                                              const QString &outCropGrowthIndicesFile, const QString &outLaiMetricsFile)
{
    QStringList args = {
        "--input", mdb1File,
        "--sg-output", sgOutFile,
        "--indices-output", outCropGrowthIndicesFile,
        "--metrics-output", outLaiMetricsFile
    };
    args += "--year";
    for(const int &year: years) {
        args += QString::number(year);
    }
    return args;
}

QStringList S4SYieldSUFeaturesHandler::GetTrendFeaturesTaskArgs(const QString &input, const std::vector<int> &years, const QString &output)
{
    QStringList args = {
        "--input", input,
        "--output", output
    };
    args += "--year";
    for(const int &year: years) {
        args += QString::number(year);
    }
    return args;
}

QStringList S4SYieldSUFeaturesHandler::GetParcelsExtractionTaskArgs(int siteId, int year, const QString &outFile)
{
    return { "-s", QString::number(siteId), "-y", QString::number(year), "-o", outFile};
}

QStringList S4SYieldSUFeaturesHandler::GetWeatherFeaturesTaskArgs(const QStringList &weatherFiles, const QString &parcelsShp,
                                                          const QString &shpIdFieldName, const QString &outDir)
{
    QStringList args = { "-v", parcelsShp, "-o", outDir, "-f", shpIdFieldName};
    args += "-i";
    args.append(weatherFiles);

    return args;
}

QStringList S4SYieldSUFeaturesHandler::GetWeatherFeaturesMergeTaskArgs(const QString &inDir, const QString &outWeatherFeatures)
{
    return { "Markers1CsvMerge", "-out", outWeatherFeatures, "-il", inDir };
}

QStringList S4SYieldSUFeaturesHandler::GetAllFeaturesMergeTaskArgs(const QString &sgListFile, const QString &trendFeatFile,
                                                           const QString &weatherFeatFile, const QString &outMergedFeatures,
                                                           const QString &sgYieldLaiFeaturesPath, const QString &suAdditionalInfosPath)
{
    return  { "-i", sgListFile,
              "-t", trendFeatFile,
              "-w", weatherFeatFile,
              "-l", sgYieldLaiFeaturesPath,
              "-a", suAdditionalInfosPath,
              "-o", outMergedFeatures,
              "-g", "0"};
}

QStringList S4SYieldSUFeaturesHandler::GetYieldFeaturesTaskArgs(const QString &inMergedFeatures, int maxYear, const QString &outYieldFeatures,
                                                        const QString &outPrevYearsYieldFeatures)
{

    return { "-i", inMergedFeatures,
             "-y", QString::number(maxYear),
             "-o", outYieldFeatures,
             "-p", outPrevYearsYieldFeatures
    };
}

QStringList S4SYieldSUFeaturesHandler::GetMergeYieldFeaturesTaskArgs(const QString &inYieldFeatures, const QString &outMergedYieldFeatures)
{

    return { "-i", inYieldFeatures, "-o", outMergedYieldFeatures};
}

void S4SYieldSUFeaturesHandler::HandleJobSubmittedImpl(EventProcessingContext &ctx,
                                                const JobSubmittedEvent &event)
{
    S4SYieldJobConfig cfg(&ctx, event, processorDescr.shortName);
    S4CMarkersDB1DataExtractStepsBuilder dataExtrStepsBuilder;
//    if (cfg.extractFeatures) {
        // we do not provide the patterns as we provide directly the custom lpisInfos
        ParcelsProductDescriptor descr = {cfg.suUniqueId, "", "", "", ""};
        dataExtrStepsBuilder.Initialize(processorDescr.shortName, ctx, cfg.parameters, event.siteId, event.jobId,
                                        {"LAI"}, true, cfg.lpisInfos, descr, cfg.dataExtractionRootDir);
//    }

    QList<TaskToSubmit> allTasksList;
    QList<std::reference_wrapper<TaskToSubmit>> allTasksListRef = CreateTasks(cfg, allTasksList, dataExtrStepsBuilder);
    SubmitTasks(ctx, cfg.event.jobId, allTasksListRef);
    NewStepList allSteps = CreateSteps(allTasksList, cfg, dataExtrStepsBuilder);
    ctx.SubmitSteps(allSteps);
}

void S4SYieldSUFeaturesHandler::HandleTaskFinishedImpl(EventProcessingContext &ctx,
                                                const TaskFinishedEvent &event)
{
    if (event.module == "yield-su-feat-product-formatter") {
        const QString &prodName = GetOutputProductName(ctx, event);
        const QString &productFolder =
            GetFinalProductFolder(ctx, event.jobId, event.siteId) + "/" + prodName;
        if (prodName != "") {
            const QString &quicklook = GetProductFormatterQuicklook(ctx, event);
            const QString &footPrint = GetProductFormatterFootprint(ctx, event);
            // Insert the product into the database
            GenericHighLevelProductHelper prdHelper(productFolder);
            int prdId = ctx.InsertProduct({ ProductType::S4SYieldSUFeatProductTypeId, event.processorId,
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
            // TODO: reinsert this but check why it still remove the folder even if the key is set to 1
            // RemoveJobFolder(ctx, event.jobId, processorDescr.shortName);
        } else {
            ctx.MarkJobFailed(event.jobId);
            Logger::error(
                QStringLiteral("Cannot insert into database the product with name %1 and folder %2")
                    .arg(prodName)
                    .arg(productFolder));
        }
    }
}

ProcessorJobDefinitionParams S4SYieldSUFeaturesHandler::GetProcessingDefinitionImpl(
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
    int startSeasonOffset = cfgValues["processor.s4s_perm_crop.start_season_offset"].value.toInt();
    seasonStartDate = seasonStartDate.addDays(startSeasonOffset);

    QDateTime startDate = seasonStartDate;
    QDateTime endDate = qScheduledDate;
    // do not pass anymore the product list but the dates
    params.jsonParameters.append("{ \"scheduled_job\": \"1\", \"start_date\": \"" + startDate.toString("yyyyMMdd") + "\", " +
                                 "\"end_date\": \"" + endDate.toString("yyyyMMdd") + "\", " +
                                 "\"season_start_date\": \"" + seasonStartDate.toString("yyyyMMdd") + "\", " +
                                 "\"season_end_date\": \"" + seasonEndDate.toString("yyyyMMdd") + "\"}");

    // Normally, we need at least 1 product available, the crop mask and the shapefile in order to
    // be able to create a S4C Permanent Crops product but if we do not return here, the schedule block waiting
    // for products (that might never happen)
    bool waitForAvailProcInputs =
        (cfgValues["processor.s4s_perm_crop.sched_wait_proc_inputs"].value.toInt() != 0);
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
        Logger::debug(QStringLiteral("Scheduled job for S4S Permanent Crops and site ID %1 with start date %2 "
                                     "and end date %3 will not be executed "
                                     "(productsNo = %4)!")
                          .arg(siteId)
                          .arg(startDate.toString())
                          .arg(endDate.toString())
                          .arg(params.productList.size()));
    }

    return params;
}

QStringList S4SYieldSUFeaturesHandler::GetProductFormatterArgs(TaskToSubmit &productFormatterTask,
                                                     const S4SYieldJobConfig &cfg, const QStringList &listFiles) {
    QString strTimePeriod = cfg.startDate.toString("yyyyMMddTHHmmss").append("_").append(cfg.endDate.toString("yyyyMMddTHHmmss"));
    QStringList additionalArgs = {"-processor.generic.files"};
    additionalArgs += listFiles;
    return GetDefaultProductFormatterArgs(*(cfg.pCtx), productFormatterTask, cfg.event.jobId, cfg.event.siteId, "S4SYIELDSUFEAT", strTimePeriod,
                                         "generic", additionalArgs, true);
}

//static bool ComparePrdsDates(const Product &prd1, const Product &prd2)
//{
//    return (prd1.created > prd2.created);
//}

ProductList S4SYieldSUFeaturesHandler::S4SYieldJobConfig::GetCropTypeProducts()
{
    ProductList cropTypePrdsList = pCtx->GetProducts(event.siteId, (int)ProductType::S4SCropTypeMappingProductTypeId,
                                                                       startDate, endDate.addDays(1));
    if (cropTypePrdsList.size() == 0) {
        pCtx->MarkJobFailed(event.jobId);
        throw std::runtime_error(QStringLiteral("Yield SU: No crop type products were found in database for site %1 and interval %2 - %3.")
                                 .arg(siteShortName)
                                 .arg(startDate.toString())
                                 .arg(endDate.toString()).toStdString());
    }
    // std::sort(cropTypePrdsList.begin(), cropTypePrdsList.end(), ComparePrdsDates);

    std::sort(cropTypePrdsList.begin(), cropTypePrdsList.end(),
                  [](const Product& a, const Product& b) {
                      return a.created < b.created;
                  });
    QSet<int> seenYears;
    ProductList result;
    for (const Product& prd : cropTypePrdsList) {
        int year = prd.created.date().year();
        if (!seenYears.contains(year)) {
            seenYears.insert(year);
            result.append(prd);
        }
    }

    return result;
}

QString S4SYieldSUFeaturesHandler::S4SYieldJobConfig::GetProcessorDirValue(const QJsonObject &parameters, const std::map<QString, QString> &configParameters,
                                                    const QString &key, const QString &siteShortName, const QString &procShortName,
                                                    const QString &defVal ) {
    QString value = ProcessorHandlerHelper::GetStringConfigValue(parameters, configParameters, key, S4S_YIELD_FEAT_CFG_PREFIX);

    if (value.size() == 0) {
        value = defVal;
    }
    value = value.replace("{site}", siteShortName);
    value = value.replace("{processor}", procShortName);

    return value;

}

