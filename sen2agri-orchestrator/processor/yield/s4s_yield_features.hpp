#pragma once

#include "processorhandler.hpp"

#include "s4s_yield_features_handler.hpp"
#include "s4s_yield_su_features_handler.hpp"

class S4SYieldFeatures : public ProcessorHandler
{
    virtual void SetProcessorDescription(const ProcessorDescription &procDescr) override;

private:
    void HandleJobSubmittedImpl(EventProcessingContext &ctx,
                                const JobSubmittedEvent &event) override;
    void HandleTaskFinishedImpl(EventProcessingContext &ctx,
                                const TaskFinishedEvent &event) override;
    ProcessorJobDefinitionParams GetProcessingDefinitionImpl(SchedulingContext &ctx, int siteId, int scheduledDate,
                                                const ConfigurationParameterValueMap &requestOverrideCfgValues) override;

    bool IsYieldSU(ExecutionContextBase &ctx, const QJsonObject &parameters, const std::map<QString, QString> &configParameters, int siteId, const QDateTime &qSeasonDate);
    QString GetSUShapefile(const QString &suDir);
    bool HasParcelsYieldEstimates(ExecutionContextBase &ctx, int siteId, const QDateTime &qSeasonDate);

private:
    // TODO add the subhandlers here
    S4SYieldFeaturesHandler m_yieldFeaturesHandler;
    S4SYieldSUFeaturesHandler m_yieldSUFeaturesHandler;
};

