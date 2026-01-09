#include <QJsonObject>

#include "s4s_yield_features.hpp"
#include "processorhandlerhelper.h"
#include "logger.hpp"

void S4SYieldFeatures::SetProcessorDescription(const ProcessorDescription &procDescr) {
    this->processorDescr = procDescr;
    m_yieldFeaturesHandler.SetProcessorDescription(procDescr);
    m_yieldSUFeaturesHandler.SetProcessorDescription(procDescr);
}

void S4SYieldFeatures::HandleJobSubmittedImpl(EventProcessingContext &ctx,
                                             const JobSubmittedEvent &event)
{
    const std::map<QString, QString> &configParameters = ctx.GetJobConfigurationParameters(event.jobId, S4S_YIELD_FEAT_CFG_PREFIX);
    const QJsonObject &parameters = QJsonDocument::fromJson(event.parametersJson.toUtf8()).object();
    const QDateTime &startDate = ProcessorHandlerHelper::GetDateTimeFromString(
                ProcessorHandlerHelper::GetStringConfigValue(parameters, configParameters, "start_date", S4S_YIELD_FEAT_CFG_PREFIX));
//    const QDateTime &endDate = ProcessorHandlerHelper::GetDateTimeFromString(
//                ProcessorHandlerHelper::GetStringConfigValue(parameters, configParameters, "end_date", S4S_YIELD_CFG_PREFIX));

    if (IsYieldSU(ctx, parameters, configParameters, event.siteId, startDate)) {
        m_yieldSUFeaturesHandler.HandleJobSubmitted(ctx, event);
    } else {
        m_yieldFeaturesHandler.HandleJobSubmitted(ctx, event);
    }
}

void S4SYieldFeatures::HandleTaskFinishedImpl(EventProcessingContext &ctx,
                                             const TaskFinishedEvent &event)
{
    this->m_yieldFeaturesHandler.HandleTaskFinished(ctx, event);
    this->m_yieldSUFeaturesHandler.HandleTaskFinished(ctx, event);
}

ProcessorJobDefinitionParams S4SYieldFeatures::GetProcessingDefinitionImpl(SchedulingContext &ctx, int siteId, int scheduledDate,
                                                          const ConfigurationParameterValueMap &requestOverrideCfgValues)
{
    ProcessorJobDefinitionParams params;
    QDateTime qScheduledDate = QDateTime::fromTime_t(scheduledDate);
    const std::map<QString, QString> &configParameters = ctx.GetConfigurationParameterValues(S4S_YIELD_FEAT_CFG_PREFIX);
    if (IsYieldSU(ctx, QJsonObject(), configParameters, siteId, qScheduledDate)) {
        return m_yieldSUFeaturesHandler.GetProcessingDefinition(ctx, siteId, scheduledDate, requestOverrideCfgValues);
    } else {
        return this->m_yieldFeaturesHandler.GetProcessingDefinition(ctx, siteId, scheduledDate, requestOverrideCfgValues);
    }
    return params;
}

bool S4SYieldFeatures::IsYieldSU(ExecutionContextBase &ctx, const QJsonObject &parameters, const std::map<QString, QString> &configParameters, int siteId, const QDateTime &qSeasonDate) {
    bool forceSU = ProcessorHandlerHelper::GetBoolConfigValue(parameters, configParameters, "force_yield_su", S4S_YIELD_FEAT_CFG_PREFIX, false);
    if (forceSU) {
        return true;
    }

    if (HasParcelsYieldEstimates(ctx, siteId, qSeasonDate)) {
        return false;
    } else {
        const QString &siteShortName = ctx.GetSiteShortName(siteId);
        // TODO: This key must be common for both Yield Features and Yield Model
        QString suPath = ProcessorHandlerHelper::GetStringConfigValue(parameters, configParameters, "su_path", S4S_YIELD_FEAT_CFG_PREFIX);

        suPath = suPath.replace("{site}", siteShortName);
        suPath = GetSUShapefile(suPath);
        if (suPath.size() > 0) {
            return true;
        }
        return false;
    }
}

QString S4SYieldFeatures::GetSUShapefile(const QString &suDir) {
    QDir directory(suDir);
    const QStringList &dirFiles = directory.entryList(QStringList() << "*.shp" ,QDir::Files);
    foreach(const QString &fileName, dirFiles) {
        return directory.filePath(fileName);
    }
    Logger::info(
        QStringLiteral("Cannot find the SU Shapefile into directory %1")
            .arg(suDir));
    return "";
}

bool S4SYieldFeatures::HasParcelsYieldEstimates(ExecutionContextBase &ctx, int siteId, const QDateTime &qSeasonDate) {
    const Season &season = GetSeason(ctx, siteId, qSeasonDate);
    const QString &siteShortName = ctx.GetSiteShortName(siteId);
    return ctx.HasParcelYieldEstimates(siteShortName, season);
}

