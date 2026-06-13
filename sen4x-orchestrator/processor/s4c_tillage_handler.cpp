#include <QJsonDocument>
#include <QJsonObject>
#include <QRegularExpression>
#include <fstream>

#include "logger.hpp"
#include "processorhandlerhelper.h"
#include "s4c_tillage_handler.hpp"

#include "products/generichighlevelproducthelper.h"
using namespace orchestrator::products;

S4CTillageHandler::S4CTillageHandler()
{
}

QList<std::reference_wrapper<TaskToSubmit>>
S4CTillageHandler::CreateTasks(QList<TaskToSubmit> &outAllTasksList)
{
    int curIdx = 0;
    outAllTasksList.append(TaskToSubmit{ "s4c-tillage-detection", { } });
    outAllTasksList.append(TaskToSubmit{ "product-formatter", {outAllTasksList[curIdx++]} });

    QList<std::reference_wrapper<TaskToSubmit>> allTasksListRef;
    for (TaskToSubmit &task : outAllTasksList) {
        allTasksListRef.append(task);
    }
    return allTasksListRef;
}

NewStepList S4CTillageHandler::CreateSteps(EventProcessingContext &ctx,
                                            const JobSubmittedEvent &event,
                                            QList<TaskToSubmit> &allTasksList,
                                            const TillageJobConfig &cfg)
{
    int curTaskIdx = 0;
    NewStepList allSteps;
    TaskToSubmit &tillageTask = allTasksList[curTaskIdx++];
    TaskToSubmit &prdFormatterTask = allTasksList[curTaskIdx++];

    const QString &prdFinalFilesDir = prdFormatterTask.GetFilePath("");
    const QString &prdFinalPath = prdFormatterTask.GetFilePath("tillage_detection.csv");

    const QStringList &tillageArgs = GetTillageTaskArgs(cfg, prdFinalPath);
    allSteps.append(CreateTaskStep(tillageTask, "S4CTillageDetection", tillageArgs));

    const QStringList &productFormatterArgs = GetProductFormatterArgs(
        prdFormatterTask, ctx, event, prdFinalFilesDir, cfg.startDate, cfg.endDate);
    allSteps.append(CreateTaskStep(prdFormatterTask, "ProductFormatter", productFormatterArgs));

    return allSteps;
}

QStringList S4CTillageHandler::GetTillageTaskArgs(const TillageJobConfig &cfg,
                                                           const QString &targetFile)
{
    QStringList tillageArgs = {
                                 "--start-date",
                                 cfg.startDate.toString("yyyy-MM-dd"),
                                 "--end-date",
                                 cfg.endDate.toString("yyyy-MM-dd"),
                                 "--mdb1-filename",
                                 cfg.mdb1PrdPath,
                                 "--output",
                                 targetFile,
                                 "--coh-thr", QString::number(cfg.coherenceThr),
                                 // "--ndvi-thr", QString::number(cfg.ndviThr),
                                 "--cr-thr", QString::number(cfg.crThr),
                                 "--s1-window-days", QString::number(cfg.s1WindowDays),
                                 "--s2-window-days", QString::number(cfg.s2WindowDays),
                                 "--amp-db-thr-vv", QString::number(cfg.ampDBThrVV),
                                 "--amp-db-thr-vh", QString::number(cfg.ampDBThrVH)
    };

    return tillageArgs;
}

QStringList S4CTillageHandler::GetProductFormatterArgs(TaskToSubmit &productFormatterTask,
                                                        EventProcessingContext &ctx,
                                                        const JobSubmittedEvent &event,
                                                        const QString &tmpPrdDir,
                                                        const QDateTime &minDate,
                                                        const QDateTime &maxDate)
{
    QString strTimePeriod = minDate.toString("yyyyMMddTHHmmss").append("_").append(maxDate.toString("yyyyMMddTHHmmss"));
    QStringList additionalArgs = {"-processor.generic.files", tmpPrdDir};
    return GetDefaultProductFormatterArgs(ctx, productFormatterTask, event.jobId, event.siteId, "S4C_TILL", strTimePeriod,
                                         "generic", additionalArgs, false, "", true);
}

void S4CTillageHandler::HandleJobSubmittedImpl(EventProcessingContext &ctx,
                                                const JobSubmittedEvent &event)
{
    TillageJobConfig cfg(&ctx, event);

    QList<TaskToSubmit> allTasksList;
    QList<std::reference_wrapper<TaskToSubmit>> allTasksListRef = CreateTasks(allTasksList);
    SubmitTasks(ctx, cfg.event.jobId, allTasksListRef);
    NewStepList allSteps = CreateSteps(ctx, event, allTasksList, cfg);
    ctx.SubmitSteps(allSteps);
}

void S4CTillageHandler::HandleTaskFinishedImpl(EventProcessingContext &ctx,
                                                const TaskFinishedEvent &event)
{
    if (event.module == "product-formatter") {
        const QString &prodName = GetOutputProductName(ctx, event);
        const QString &productFolder =
            GetFinalProductFolder(ctx, event.jobId, event.siteId) + "/" + prodName;
        if (prodName != "") {
            ctx.MarkJobFinished(event.jobId);
            const QString &quicklook = GetProductFormatterQuicklook(ctx, event);
            const QString &footPrint = GetProductFormatterFootprint(ctx, event);
            // Insert the product into the database
            GenericHighLevelProductHelper prdHelper(productFolder);
            int prdId = ctx.InsertProduct({ ProductType::S4CTillageDetectionProductTypeId, event.processorId,
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
        } else {
            ctx.MarkJobFailed(event.jobId);
            Logger::error(
                QStringLiteral("Cannot insert into database the product with name %1 and folder %2")
                    .arg(prodName)
                    .arg(productFolder));
        }
        // Now remove the job folder containing temporary files
        RemoveJobFolder(ctx, event.jobId, processorDescr.shortName);
    }
}

ProcessorJobDefinitionParams S4CTillageHandler::GetProcessingDefinitionImpl(
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
        Logger::debug(QStringLiteral("Scheduler Tillage: Error getting season start dates for "
                                     "site %1 for scheduled date %2!")
                          .arg(siteId)
                          .arg(qScheduledDate.toString()));
        return params;
    }

    QDateTime limitDate = seasonEndDate.addMonths(2);
    if (qScheduledDate > limitDate) {
        Logger::debug(QStringLiteral("Scheduler Tillage: Error scheduled date %1 greater than the "
                                     "limit date %2 for site %3!")
                          .arg(qScheduledDate.toString())
                          .arg(limitDate.toString())
                          .arg(siteId));
        return params;
    }

    ConfigurationParameterValueMap cfgValues =
        ctx.GetConfigurationParameters(S4C_TILLAGE_CFG_PREFIX, siteId, requestOverrideCfgValues);
    // we might have an offset in days from starting the downloading products to start the S4S L4A
    // production
    int startSeasonOffset = cfgValues[QStringLiteral(S4C_TILLAGE_CFG_PREFIX) + "start_season_offset"].value.toInt();
    seasonStartDate = seasonStartDate.addDays(startSeasonOffset);

    QDateTime startDate = seasonStartDate;
    QDateTime endDate = qScheduledDate;
    // do not pass anymore the product list but the dates
    params.jsonParameters.append("{ \"scheduled_job\": \"1\", \"start_date\": \"" + startDate.toString("yyyyMMdd") + "\", " +
                                 "\"end_date\": \"" + endDate.toString("yyyyMMdd") + "\", " +
                                 "\"season_start_date\": \"" + seasonStartDate.toString("yyyyMMdd") + "\", " +
                                 "\"season_end_date\": \"" + seasonEndDate.toString("yyyyMMdd") + "\"}");

    params.isValid = true;
    if (!CheckAllAncestorProductCreation(ctx, siteId, ProductType::S4CTillageDetectionProductTypeId, startDate, endDate)) {
        // do not trigger yet the schedule.
        params.schedulingFlags = SchedulingFlags::SCH_FLG_RETRY_LATER;
        Logger::debug(QStringLiteral("Scheduled job for S4S_L4A and site ID %1 with start date %2 and end date %3 will "
                                     "not be executed (retried later) ")
                .arg(siteId)
                .arg(startDate.toString())
                .arg(endDate.toString()));
    } else {
        Logger::debug(QStringLiteral("Executing scheduled S4S_L4A job for site ID %1 with start date %2 and end date %3!")
                          .arg(siteId)
                          .arg(startDate.toString())
                      .arg(endDate.toString()));
    }

    return params;
}
