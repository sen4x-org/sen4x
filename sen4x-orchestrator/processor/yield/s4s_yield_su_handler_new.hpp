#pragma once

#include "processorhandler.hpp"
#include "optional.hpp"
#include "../s4c_mdb1_dataextract_steps_builder.hpp"
#include "../products/generichighlevelproducthelper.h"
#include "s4s_yield_common.h"

class S4SYieldSUHandlerNew : public ProcessorHandler
{
    typedef struct S4SYieldJobConfig {
        S4SYieldJobConfig(EventProcessingContext *pContext, const JobSubmittedEvent &evt)
            : event(evt), isScheduled(false) {
            pCtx = pContext;
            siteShortName = pContext->GetSiteShortName(evt.siteId);
            configParameters = pCtx->GetJobConfigurationParameters(evt.jobId, S4S_YIELD_CFG_PREFIX);
            parameters = QJsonDocument::fromJson(evt.parametersJson.toUtf8()).object();

            const ProductList &yfPrds = ProcessorHandler::GetInputProducts(*(pCtx), parameters, configParameters, evt.siteId,
                                                                         ProductType::S4SYieldSUFeatProductTypeId,
                                                                         S4S_YIELD_CFG_PREFIX, &startDate, &endDate);
            QList<ProductDetails> prdDetailsList = ProcessorHandlerHelper::GetProductDetails(yfPrds, *pCtx);
            if (prdDetailsList.size() == 0) {
                pCtx->MarkJobFailed(event.jobId);
                throw std::runtime_error(QStringLiteral("Yield: Could not find any input yield features product for site %1.")
                                         .arg(siteShortName).toStdString());
            }
            std::sort(prdDetailsList.begin(), prdDetailsList.end(),
                      [](const ProductDetails &a, const ProductDetails &b) {
                            const auto &pa = a.GetProduct();
                            const auto &pb = b.GetProduct();
                            if (pa.created != pb.created)
                                return pa.created > pb.created;   // descending by created
                            return pa.inserted > pb.inserted;     // descending by inserted
                      });

            const SeasonList &ss = pContext->GetSiteSeasons(evt.siteId);
            for (const auto &prdDetails : prdDetailsList) {
                orchestrator::products::GenericHighLevelProductHelper prdHelper(prdDetails.GetProduct().name);
                if(prdHelper.IsValid()) {
                    if (prdHelper.GetStartDate() < startDate) {
                        startDate = prdHelper.GetStartDate();
                    }
                    if (prdHelper.GetStartDate() > endDate) {
                        endDate = prdHelper.GetEndDate();
                    }
                    const QDate &dt = prdHelper.GetStartDate().date();
                    for (const Season &s: ss) {
                        if (dt >= s.startDate && dt < s.endDate.addDays(1)) {
                            if (s.name.size() == 0) {
                                pCtx->MarkJobFailed(event.jobId);
                                throw std::runtime_error(QStringLiteral("Yield Features: No valid season found for site %1 and date %2.")
                                                         .arg(siteShortName)
                                                         .arg(dt.toString()).toStdString());
                            }

                            bool exists = std::any_of(seasons.begin(), seasons.end(),
                                                      [s](const Season &obj) {
                                                          return obj.seasonId == s.seasonId;
                                                      });
                            if (!exists) {
                                seasons.append(s);
                                yieldFeatPrds.push_back(QDir(QDir(prdDetails.GetProduct().fullPath).filePath("VECTOR_DATA")).filePath("yield_features.csv"));
                                mergePrevYearsYieldFeatOutPath.push_back(QDir(QDir(prdDetails.GetProduct().fullPath).filePath("VECTOR_DATA")).filePath("merged_prev_years_yield_features.csv"));
                            }
                            break;
                        }
                    }
                }
            }

            // ////////////////////////////////
            // TODO: Not realy used, to be removed
            QSet<int> yearSet;
            for (const auto &prd : prdDetailsList) {
                yearSet.insert(prd.GetProduct().created.date().year());
            }
            years.reserve(yearSet.size());
            auto yearsList = yearSet.values();
            std::copy(yearsList.begin(), yearsList.end(), std::back_inserter(years));
            std::sort(years.begin(), years.end());
            // ////////////////////////////////
        }

        QString GetProcessorDirValue(const QJsonObject &parameters, const std::map<QString, QString> &configParameters,
                                     const QString &key, const QString &siteShortName, const QString &procShortName, const QString &defVal );

        EventProcessingContext *pCtx;
        JobSubmittedEvent event;

        QString siteShortName;
        QDateTime startDate;
        QDateTime endDate;
        QList<Season> seasons;
        QStringList yieldFeatPrds;
        QStringList mergePrevYearsYieldFeatOutPath;

        std::map<QString, QString> configParameters;
        QJsonObject parameters;
        bool isScheduled;
        std::vector<int> years;     // TODO: Not realy used, to be removed

    } S4SYieldJobConfig;

private:
    void HandleJobSubmittedImpl(EventProcessingContext &ctx,
                                const JobSubmittedEvent &event) override;
    void HandleTaskFinishedImpl(EventProcessingContext &ctx,
                                const TaskFinishedEvent &event) override;

    ProcessorJobDefinitionParams GetProcessingDefinitionImpl(SchedulingContext &ctx, int siteId, int scheduledDate,
                                                const ConfigurationParameterValueMap &requestOverrideCfgValues) override;
    QList<std::reference_wrapper<TaskToSubmit>> CreateTasks(const S4SYieldJobConfig &cfg, QList<TaskToSubmit> &outAllTasksList);
    NewStepList CreateSteps(QList<TaskToSubmit> &allTasksList, const S4SYieldJobConfig &cfg);

    QStringList GetCropTypesExtractionTaskArgs(int siteId, int seasonId, const QString &outCropTypesFile);
    QStringList GetYieldModelTaskArgs(const S4SYieldJobConfig &cfg, const QString &cropCodesFile, const QString &inYieldFeatures, const QString &inPrevYearsYieldFeatures, const QString &trainingFeaturesFile,
                                      const QString &outYieldEstimates, const QString &outYieldSUEstimates);

    QString GetProcessorDirValue(const QJsonObject &parameters, const std::map<QString, QString> &configParameters,
                                 const QString &key, const QString &siteShortName, const QString &defVal = "");
    QStringList GetProductFormatterArgs(TaskToSubmit &productFormatterTask, const S4SYieldJobConfig &cfg, const QStringList &listFiles);
};

