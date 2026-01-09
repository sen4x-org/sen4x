#include <QJsonDocument>
#include <QJsonObject>
#include <QRegularExpression>
#include <fstream>

#include "logger.hpp"
#include "processorhandlerhelper.h"
#include "s4s_yield_su_handler_new.hpp"
#include "processor/s4c_utils.hpp"
#include "stepexecutiondecorator.h"

#include "processor/products/generichighlevelproducthelper.h"
using namespace orchestrator::products;

// TODO: These defines shoule be extracted from config
static QStringList YIELD_INPUT_MARKER_NAMES = {"LAI"};

QList<std::reference_wrapper<TaskToSubmit>>
S4SYieldSUHandlerNew::CreateTasks(const S4SYieldJobConfig & /* cfg */, QList<TaskToSubmit> &outAllTasksList)
{
    int curTaskIdx = 0;
    outAllTasksList.append(TaskToSubmit{ "s4s-yield-crop-types-extraction", {} });
    int yieldCTExtrIdx = curTaskIdx++;

    // QList<std::reference_wrapper<const TaskToSubmit>> parentTasks = {/*outAllTasksList[yieldReferenceExtrIdx], */outAllTasksList[yieldCTExtrIdx], outAllTasksList[yieldFeatExtrIdx]};
    outAllTasksList.append(TaskToSubmit{ "s4s-yield-su-model-wrp", {outAllTasksList[yieldCTExtrIdx] } } );
    int yieldModelIdx = curTaskIdx++;

    outAllTasksList.append(TaskToSubmit{ "product-formatter", {outAllTasksList[yieldModelIdx]} });

    QList<std::reference_wrapper<TaskToSubmit>> allTasksListRef;
    for (TaskToSubmit &task : outAllTasksList) {
        allTasksListRef.append(task);
    }
    return allTasksListRef;
}

NewStepList S4SYieldSUHandlerNew::CreateSteps(QList<TaskToSubmit> &allTasksList,const S4SYieldJobConfig &cfg)
{
    int curTaskIdx = 0;
    NewStepList allSteps;
    QStringList prdFormatterFiles;

    int ctExtrTskId = curTaskIdx++;
    int yieldModelTskId = curTaskIdx++;
    TaskToSubmit &productFormatterTask = allTasksList[curTaskIdx++];

    TaskToSubmit &ctExtrTask = allTasksList[ctExtrTskId];
    const QString &cropTypes = ctExtrTask.GetFilePath("crop_types.csv");

    const QStringList &cropTypesExtractionArgs = GetCropTypesExtractionTaskArgs(cfg.event.siteId, cfg.seasons.at(0).seasonId, cropTypes);
    allSteps.append(CreateTaskStep(ctExtrTask, "CropTypesExtraction", cropTypesExtractionArgs));

    TaskToSubmit &yieldModelTask = allTasksList[yieldModelTskId];
    const QString &yieldModelOutputPath = yieldModelTask.GetFilePath("");
    const QString &yieldEstimateOutputPath = yieldModelTask.GetFilePath("yield_estimate.csv");
    const QString &yieldStatisticalUnitEstimateOutputPath = yieldModelTask.GetFilePath("yield_statistical_units_estimate.csv");
    const QStringList &yieldModelExtractionArgs = GetYieldModelTaskArgs(cfg, /* yieldReference, */ cropTypes,
                                                                        cfg.yieldFeatPrds.at(0), cfg.mergePrevYearsYieldFeatOutPath.at(0),
                                                                        yieldEstimateOutputPath, yieldStatisticalUnitEstimateOutputPath);
    allSteps.append(CreateTaskStep(yieldModelTask, "YieldModel", yieldModelExtractionArgs));
    // we append the full directory containing all resulted files
    prdFormatterFiles.append(yieldModelOutputPath);

    const QStringList &productFormatterArgs = GetProductFormatterArgs(productFormatterTask, cfg, prdFormatterFiles);
    allSteps.append(CreateTaskStep(productFormatterTask, "ProductFormatter", productFormatterArgs));

    return allSteps;
}

QStringList S4SYieldSUHandlerNew::GetCropTypesExtractionTaskArgs(int siteId, int seasonId, const QString &outCropTypesFile)
{
    return { "-s", QString::number(siteId),
             "--season-id", QString::number(seasonId),
             "-o", outCropTypesFile
    };
}

QStringList S4SYieldSUHandlerNew::GetYieldModelTaskArgs(const S4SYieldJobConfig &cfg, const QString & cropCodesFile, const QString & inYieldFeatures,
                                                     const QString &inPrevYearsYieldFeatures, const QString &outYieldEstimates, const QString & /* outYieldSUEstimates */)
{
    const QString &algo = ProcessorHandlerHelper::GetStringConfigValue(cfg.parameters, cfg.configParameters,
                                                                               "algorithm", S4S_YIELD_CFG_PREFIX);
    const QString &selectionType = ProcessorHandlerHelper::GetStringConfigValue(cfg.parameters, cfg.configParameters,
                                                                               "selection-type", S4S_YIELD_CFG_PREFIX);
    QString maxAutomaticFeaturesNo;
    if (selectionType == "automatic") {
        maxAutomaticFeaturesNo = ProcessorHandlerHelper::GetStringConfigValue(cfg.parameters, cfg.configParameters,
                                                                                   "max-automatic-features-no", S4S_YIELD_CFG_PREFIX);
    }
    QStringList manualFeatures;
    if (selectionType == "manual") {
        const QString &strManualFeatures = ProcessorHandlerHelper::GetStringConfigValue(cfg.parameters, cfg.configParameters,
                                                                                   "manual-selection-features", S4S_YIELD_CFG_PREFIX);
#if QT_VERSION >= QT_VERSION_CHECK(5, 14, 0)
        manualFeatures = strManualFeatures.split(',', Qt::SkipEmptyParts);
#else
        manualFeatures = strManualFeatures.split(',', QString::SkipEmptyParts);
#endif
    }

//        "-a", "--algo", required=False, default="rf", help="The algorithm to be used. lm - LinerarRegression, svm - SupportVectortMachine. Default rf = RandomForest", choices=['rf', 'lm', 'svm']
//        "-s", "--selection", required=False, default="none", help="The selection mode. Possible values: automatic or manual or none", choices=['none', 'manual', 'automatic']
//        "-m", "--manual-selection-features", required=False, help="The selection features list for the manual mode", nargs='+', type=str
//        "-n", "--max-automatic-features-no", required=False, help="The maximum number of selection features for the automatic mode", type=int, default = 44
//        "-i", "--input-features", required=True, help="The input features file"
//        "-r", "--yield-reference", required=True, help="The input yield reference file"
//        "-u", "--statistical-unit-fields", required=True, help="The input statistical unit fields mapping file"
//        "-o", "--output", required=True, help="The output estimation file"
//        "-e", "--output-statistical-units-estimate", required=True, help="The output for statistical units estimation file"


    QStringList args =
    {
        "-i", inYieldFeatures,
        "-o", outYieldEstimates,
        // "-e", outYieldSUEstimates,
        "-r", inPrevYearsYieldFeatures,
        "-c", cropCodesFile
    };
    if (algo.size() > 0) {
        args += "-a";
        args.append(algo);
    }
    if (selectionType.size() > 0) {
        args += "-s";
        args.append(selectionType);
    }
    if (manualFeatures.size() > 0) {
        args += "-m";
        args.append(manualFeatures);
    }
    if (maxAutomaticFeaturesNo.size() > 0 && maxAutomaticFeaturesNo.toInt() > 0)
    {
        args += "-n";
        args += maxAutomaticFeaturesNo;
    }

    return args;
}



void S4SYieldSUHandlerNew::HandleJobSubmittedImpl(EventProcessingContext &ctx,
                                                const JobSubmittedEvent &event)
{
    S4SYieldJobConfig cfg(&ctx, event);
    QList<TaskToSubmit> allTasksList;
    QList<std::reference_wrapper<TaskToSubmit>> allTasksListRef = CreateTasks(cfg, allTasksList);
    SubmitTasks(ctx, cfg.event.jobId, allTasksListRef);
    NewStepList allSteps = CreateSteps(allTasksList, cfg);
    ctx.SubmitSteps(allSteps);
}

void S4SYieldSUHandlerNew::HandleTaskFinishedImpl(EventProcessingContext &ctx,
                                                const TaskFinishedEvent &event)
{
    if (event.module == "yield-su-product-formatter") {
        const QString &prodName = GetOutputProductName(ctx, event);
        const QString &productFolder =
            GetFinalProductFolder(ctx, event.jobId, event.siteId) + "/" + prodName;
        if (prodName != "") {
            const QString &quicklook = GetProductFormatterQuicklook(ctx, event);
            const QString &footPrint = GetProductFormatterFootprint(ctx, event);
            // Insert the product into the database
            GenericHighLevelProductHelper prdHelper(productFolder);
            int prdId = ctx.InsertProduct({ ProductType::S4SYieldSUProductTypeId, event.processorId,
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

ProcessorJobDefinitionParams S4SYieldSUHandlerNew::GetProcessingDefinitionImpl(
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
        ctx.GetConfigurationParameters(S4S_YIELD_CFG_PREFIX, siteId, requestOverrideCfgValues);
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

QStringList S4SYieldSUHandlerNew::GetProductFormatterArgs(TaskToSubmit &productFormatterTask,
                                                     const S4SYieldJobConfig &cfg, const QStringList &listFiles) {
    QString strTimePeriod = cfg.startDate.toString("yyyyMMddTHHmmss").append("_").append(cfg.endDate.toString("yyyyMMddTHHmmss"));
    QStringList additionalArgs = {"-processor.generic.files"};
    additionalArgs += listFiles;
    return GetDefaultProductFormatterArgs(*(cfg.pCtx), productFormatterTask, cfg.event.jobId, cfg.event.siteId, "S4SYIELDSU", strTimePeriod,
                                         "generic", additionalArgs, true);
}

static bool ComparePrdsDates(const Product &prd1, const Product &prd2)
{
    return (prd1.created < prd2.created);
}

QString S4SYieldSUHandlerNew::S4SYieldJobConfig::GetCropTypeProductPath()
{
    ProductList cropTypePrdsList = pCtx->GetProducts(event.siteId, (int)ProductType::S4SCropTypeMappingProductTypeId,
                                                                       startDate, endDate);
    if (cropTypePrdsList.size() == 0) {
        pCtx->MarkJobFailed(event.jobId);
        throw std::runtime_error(QStringLiteral("Yield SU: No crop type products were found in database for site %1 and interval %2 - %3.")
                                 .arg(siteShortName)
                                 .arg(startDate.toString())
                                 .arg(endDate.toString()).toStdString());
    }
    std::sort(cropTypePrdsList.begin(), cropTypePrdsList.end(), ComparePrdsDates);
    return cropTypePrdsList.at(0).fullPath;
}


QString S4SYieldSUHandlerNew::S4SYieldJobConfig::GetProcessorDirValue(const QJsonObject &parameters, const std::map<QString, QString> &configParameters,
                                                    const QString &key, const QString &siteShortName, const QString &procShortName,
                                                    const QString &defVal ) {
    QString value = ProcessorHandlerHelper::GetStringConfigValue(parameters, configParameters, key, S4S_YIELD_CFG_PREFIX);

    if (value.size() == 0) {
        value = defVal;
    }
    value = value.replace("{site}", siteShortName);
    value = value.replace("{processor}", procShortName);

    return value;

}

