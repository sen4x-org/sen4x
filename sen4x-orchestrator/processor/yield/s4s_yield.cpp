#include <QJsonObject>

#include "s4s_yield.hpp"
#include "processorhandlerhelper.h"
#include "logger.hpp"

void S4SYield::SetProcessorDescription(const ProcessorDescription &procDescr) {
    this->processorDescr = procDescr;
    m_yieldHandler.SetProcessorDescription(procDescr);
    m_yieldSUHandlerNew.SetProcessorDescription(procDescr);
}

void S4SYield::HandleJobSubmittedImpl(EventProcessingContext &ctx,
                                             const JobSubmittedEvent &event)
{
    const std::map<QString, QString> &configParameters = ctx.GetJobConfigurationParameters(event.jobId, S4S_YIELD_CFG_PREFIX);
    const QJsonObject &parameters = QJsonDocument::fromJson(event.parametersJson.toUtf8()).object();

    QDateTime startDate, endDate;
    ProductList yieldFeatPrds = ProcessorHandler::GetInputProducts(ctx, parameters, configParameters, event.siteId,
                                                                 ProductType::S4SYieldFeatProductTypeId,
                                                                 S4S_YIELD_CFG_PREFIX, &startDate, &endDate);
    ProductList yieldSuFeatPrds = ProcessorHandler::GetInputProducts(ctx, parameters, configParameters, event.siteId,
                                                                 ProductType::S4SYieldSUFeatProductTypeId,
                                                                 S4S_YIELD_CFG_PREFIX, &startDate, &endDate);
    if (yieldFeatPrds.size() == 0 && yieldSuFeatPrds.size() == 0) {
        ctx.MarkJobFailed(event.jobId);
        throw std::runtime_error(QStringLiteral("Yield: Could not find any input yield features products or yield SU features products for site %1.")
                                 .arg(event.siteId).toStdString());
    }
    std::sort(yieldFeatPrds.begin(), yieldFeatPrds.end(),
              [](const Product &a, const Product &b) {
                  return a.inserted > b.inserted;
              });
    std::sort(yieldSuFeatPrds.begin(), yieldSuFeatPrds.end(),
              [](const Product &a, const Product &b) {
                  return a.inserted > b.inserted;
              });

    if (IsYieldSU(ctx, parameters, configParameters, event.siteId, endDate, yieldFeatPrds, yieldSuFeatPrds, false)) {
        m_yieldSUHandlerNew.HandleJobSubmitted(ctx, event);
    } else {
        m_yieldHandler.HandleJobSubmitted(ctx, event);
    }
}

void S4SYield::HandleTaskFinishedImpl(EventProcessingContext &ctx,
                                             const TaskFinishedEvent &event)
{
    this->m_yieldHandler.HandleTaskFinished(ctx, event);
    this->m_yieldSUHandlerNew.HandleTaskFinished(ctx, event);
}

ProcessorJobDefinitionParams S4SYield::GetProcessingDefinitionImpl(SchedulingContext &ctx, int siteId, int scheduledDate,
                                                          const ConfigurationParameterValueMap &requestOverrideCfgValues)
{
    ProcessorJobDefinitionParams params;
    QDateTime qScheduledDate = QDateTime::fromTime_t(scheduledDate);
    const std::map<QString, QString> &configParameters = ctx.GetConfigurationParameterValues(S4S_YIELD_CFG_PREFIX);

    if (IsYieldSU(ctx, QJsonObject(), configParameters, siteId, qScheduledDate, ProductList(), ProductList(), true)) {
        return m_yieldSUHandlerNew.GetProcessingDefinition(ctx, siteId, scheduledDate, requestOverrideCfgValues);
    } else {
        return this->m_yieldHandler.GetProcessingDefinition(ctx, siteId, scheduledDate, requestOverrideCfgValues);
    }
    return params;
}

bool S4SYield::IsYieldSU(ExecutionContextBase &ctx, const QJsonObject &parameters, const std::map<QString, QString> &configParameters, int siteId, const QDateTime &qSeasonDate,
                         const ProductList &yieldFeatPrds, const ProductList &yieldSuFeatPrds, bool scheduledJob) {
    bool forceSU = ProcessorHandlerHelper::GetBoolConfigValue(parameters, configParameters, "force_yield_su", S4S_YIELD_CFG_PREFIX, false);
    if (forceSU) {
        return true;
    }

    if (HasParcelsYieldEstimates(ctx, siteId, qSeasonDate) &&
            (scheduledJob || yieldFeatPrds.size() > 0)) {
        return false;
    } else {
        if (!scheduledJob && yieldSuFeatPrds.size() > 0) {
            return false;
        }
        // fallback
        const QString &siteShortName = ctx.GetSiteShortName(siteId);
        // TODO: This key must be common for both Yield Features and Yield Model
        QString suPath = ProcessorHandlerHelper::GetStringConfigValue(parameters, configParameters, "su_path", S4S_YIELD_CFG_PREFIX);

        suPath = suPath.replace("{site}", siteShortName);
        suPath = GetSUShapefile(suPath);
        if (suPath.size() > 0) {
            return true;
        }
        return false;
    }
}

QString S4SYield::GetSUShapefile(const QString &suDir) {
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

bool S4SYield::HasParcelsYieldEstimates(ExecutionContextBase &ctx, int siteId, const QDateTime &qSeasonDate) {
    const Season &season = GetSeason(ctx, siteId, qSeasonDate);
    const QString &siteShortName = ctx.GetSiteShortName(siteId);
    return ctx.HasParcelYieldEstimates(siteShortName, season);
}

