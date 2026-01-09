#pragma once

#include "processorhandler.hpp"

#include "s4s_yield_handler_new.hpp"
#include "s4s_yield_su_handler_new.hpp"

class S4SYield : public ProcessorHandler
{
    virtual void SetProcessorDescription(const ProcessorDescription &procDescr) override;

private:
    void HandleJobSubmittedImpl(EventProcessingContext &ctx,
                                const JobSubmittedEvent &event) override;
    void HandleTaskFinishedImpl(EventProcessingContext &ctx,
                                const TaskFinishedEvent &event) override;
    ProcessorJobDefinitionParams GetProcessingDefinitionImpl(SchedulingContext &ctx, int siteId, int scheduledDate,
                                                const ConfigurationParameterValueMap &requestOverrideCfgValues) override;

    bool IsYieldSU(ExecutionContextBase &ctx, const QJsonObject &parameters, const std::map<QString, QString> &configParameters, int siteId, const QDateTime &qSeasonDate,
                   const ProductList &yieldFeatPrds, const ProductList &yieldSuFeatPrds, bool scheduledJob);
    QString GetSUShapefile(const QString &suDir);
    bool HasParcelsYieldEstimates(ExecutionContextBase &ctx, int siteId, const QDateTime &qSeasonDate);

private:
    // TODO add the subhandlers here
    S4SYieldHandlerNew m_yieldHandler;
    S4SYieldSUHandlerNew m_yieldSUHandlerNew;
};


