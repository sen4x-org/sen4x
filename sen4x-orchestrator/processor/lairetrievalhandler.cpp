#include <QJsonDocument>
#include <QJsonObject>
#include <QRegularExpression>
#include <fstream>

#include "lairetrievalhandler.hpp"
#include "processorhandlerhelper.h"
#include "json_conversions.hpp"
#include "logger.hpp"

// The number of tasks that are executed for each product before executing time series tasks
#define LAI_TASKS_PER_PRODUCT       6
#define MODEL_GEN_TASKS_PER_PRODUCT 4
#define CUT_TASKS_NO                5

#define DEFAULT_GENERATED_SAMPLES_NO    "40000"
#define DEFAULT_NOISE_VAR               "0.01"
#define DEFAULT_BEST_OF                 "1"
#define DEFAULT_REGRESSOR               "nn"

void LaiRetrievalHandler::SetProcessorDescription(const ProcessorDescription &procDescr) {
    this->processorDescr = procDescr;
    m_l3bHandler.SetProcessorDescription(procDescr);
    m_l3bHandlerNew.SetProcessorDescription(procDescr);
    m_l3bHandlerIndividual.SetProcessorDescription(procDescr);
    m_procPrefix = "processor." + processorDescr.shortName + ".";
}

void LaiRetrievalHandler::HandleJobSubmittedImpl(EventProcessingContext &ctx,
                                             const JobSubmittedEvent &event)
{
    const std::map<QString, QString> &configParameters = ctx.GetJobConfigurationParameters(event.jobId, m_procPrefix);

    if (IsNewLaiMonoDateVersion(configParameters)) {
        if (IsIndividualIndicatorVersion(configParameters)) {
            m_l3bHandlerIndividual.HandleJobSubmitted(ctx, event);
        } else {
            m_l3bHandlerNew.HandleJobSubmitted(ctx, event);
        }
    } else {
        m_l3bHandler.HandleJobSubmitted(ctx, event);
    }
}

void LaiRetrievalHandler::HandleTaskFinishedImpl(EventProcessingContext &ctx,
                                             const TaskFinishedEvent &event)
{
    const std::map<QString, QString> &configParameters = ctx.GetJobConfigurationParameters(event.jobId, m_procPrefix);
    if (IsNewLaiMonoDateVersion(configParameters)) {
        if (IsIndividualIndicatorVersion(configParameters)) {
            this->m_l3bHandlerIndividual.HandleTaskFinished(ctx, event);
        } else {
            this->m_l3bHandler.HandleTaskFinished(ctx, event);
        }
    } else {
        this->m_l3bHandlerNew.HandleTaskFinished(ctx, event);
    }
}

ProcessorJobDefinitionParams LaiRetrievalHandler::GetProcessingDefinitionImpl(SchedulingContext &ctx, int siteId, int scheduledDate,
                                                          const ConfigurationParameterValueMap &requestOverrideCfgValues)
{
    ProcessorJobDefinitionParams params;

    std::map<QString, QString> configParameters = ctx.GetConfigurationParameterValues(m_procPrefix);
    if (IsNewLaiMonoDateVersion(configParameters)) {
        if (IsIndividualIndicatorVersion(configParameters)) {
            return m_l3bHandlerIndividual.GetProcessingDefinition(ctx, siteId, scheduledDate, requestOverrideCfgValues);
        } else {
            return m_l3bHandlerNew.GetProcessingDefinition(ctx, siteId, scheduledDate, requestOverrideCfgValues);
        }
    } else {
        return this->m_l3bHandler.GetProcessingDefinition(ctx, siteId, scheduledDate, requestOverrideCfgValues);
    }
    return params;
}

bool LaiRetrievalHandler::IsNewLaiMonoDateVersion(const std::map<QString, QString> &configParameters) {
    return ProcessorHandlerHelper::GetBoolConfigValue(QJsonObject(), configParameters, "lai.use_inra_version", m_procPrefix);
}

bool LaiRetrievalHandler::IsIndividualIndicatorVersion(const std::map<QString, QString> &configParameters) {
    return ProcessorHandlerHelper::GetBoolConfigValue(QJsonObject(), configParameters, "create_individual_indicators", m_procPrefix);
}
