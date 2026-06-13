#pragma once

#include "processorhandler.hpp"
#include "optional.hpp"

#define S4C_TILLAGE_CFG_PREFIX "processor.s4c_l4c_tillage."

class S4CTillageHandler : public ProcessorHandler
{

    typedef struct TillageJobConfig {
        TillageJobConfig(EventProcessingContext *pContext, const JobSubmittedEvent &evt)
            : event(evt) {
            pCtx = pContext;
            siteShortName = pContext->GetSiteShortName(evt.siteId);
            configParameters = pCtx->GetJobConfigurationParameters(evt.jobId, S4C_TILLAGE_CFG_PREFIX);
            parameters = QJsonDocument::fromJson(evt.parametersJson.toUtf8()).object();

            startDate = ProcessorHandlerHelper::GetDateTimeFromString(
                        ProcessorHandlerHelper::GetStringConfigValue(parameters, configParameters, "start_date", S4C_TILLAGE_CFG_PREFIX));
            endDate = ProcessorHandlerHelper::GetDateTimeFromString(
                        ProcessorHandlerHelper::GetStringConfigValue(parameters, configParameters, "end_date", S4C_TILLAGE_CFG_PREFIX));

            const ProductList &mdb1PrdsList = pCtx->GetProducts(event.siteId, (int)ProductType::S4MDB1ProductTypeId,
                                                                               startDate, endDate.addDays(1));
            if (mdb1PrdsList.size() == 0) {
                pCtx->MarkJobFailed(event.jobId);
                throw std::runtime_error(QStringLiteral("Bare Soil: No MDB1 products were found in database for site %1 and interval %2 - %3.")
                                         .arg(siteShortName)
                                         .arg(startDate.toString())
                                         .arg(endDate.toString()).toStdString());
            }
            mdb1PrdPath = mdb1PrdsList.at(mdb1PrdsList.size()-1).fullPath;


            crThr = ProcessorHandlerHelper::GetFloatConfigValue(parameters, configParameters, "cr_thr", S4C_TILLAGE_CFG_PREFIX, 0.5);
            coherenceThr = ProcessorHandlerHelper::GetFloatConfigValue(parameters, configParameters, "coherence_thr", S4C_TILLAGE_CFG_PREFIX, 0.2);
            //ndviThr = ProcessorHandlerHelper::GetFloatConfigValue(parameters, configParameters, "ndvi_thr", S4C_TILLAGE_CFG_PREFIX, 0.2);
            s1WindowDays = ProcessorHandlerHelper::GetIntConfigValue(parameters, configParameters, "s1_window_days", S4C_TILLAGE_CFG_PREFIX, 7);
            s2WindowDays = ProcessorHandlerHelper::GetIntConfigValue(parameters, configParameters, "s2_window_days", S4C_TILLAGE_CFG_PREFIX, 10);
            ampDBThrVV = ProcessorHandlerHelper::GetFloatConfigValue(parameters, configParameters, "amp_db_thr_vv", S4C_TILLAGE_CFG_PREFIX, -4);
            ampDBThrVH = ProcessorHandlerHelper::GetFloatConfigValue(parameters, configParameters, "amp_db_thr_vh", S4C_TILLAGE_CFG_PREFIX, -10);
        }

        EventProcessingContext *pCtx;
        JobSubmittedEvent event;

        QString siteShortName;
        QDateTime startDate;
        QDateTime endDate;
        QString mdb1PrdPath;

        float crThr;
        float coherenceThr;
        // float ndviThr;
        float ampDBThrVV;
        float ampDBThrVH;
        int s1WindowDays;
        int s2WindowDays;

        QMap<QString, QString> mapCfgValues;
        std::map<QString, QString> configParameters;
        QJsonObject parameters;

    } TillageJobConfig;

public:
    S4CTillageHandler();

private:
    void HandleJobSubmittedImpl(EventProcessingContext &ctx,
                                const JobSubmittedEvent &event) override;
    void HandleTaskFinishedImpl(EventProcessingContext &ctx,
                                const TaskFinishedEvent &event) override;

    ProcessorJobDefinitionParams GetProcessingDefinitionImpl(SchedulingContext &ctx, int siteId, int scheduledDate,
                                                const ConfigurationParameterValueMap &requestOverrideCfgValues) override;
    QList<std::reference_wrapper<TaskToSubmit>> CreateTasks(QList<TaskToSubmit> &outAllTasksList);
    NewStepList CreateSteps(EventProcessingContext &ctx, const JobSubmittedEvent &event, QList<TaskToSubmit> &allTasksList,
                            const TillageJobConfig &cfg);
    QStringList GetTillageTaskArgs(const TillageJobConfig &cfg, const QString &targetFile);
    QStringList GetProductFormatterArgs(TaskToSubmit &productFormatterTask, EventProcessingContext &ctx,
                                        const JobSubmittedEvent &event, const QString &tmpPrdDir,
                                        const QDateTime &minDate, const QDateTime &maxDate);
};
