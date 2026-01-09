#pragma once

#include "processorhandler.hpp"
#include "optional.hpp"
#include "s4s_yield_common.h"
#include "../s4c_mdb1_dataextract_steps_builder.hpp"
#include "../products/generichighlevelproducthelper.h"
#include "logger.hpp"

class S4SYieldFeaturesHandler : public ProcessorHandler
{
    typedef struct S4SYieldJobConfig {
        S4SYieldJobConfig(EventProcessingContext *pContext, const JobSubmittedEvent &evt, const QString &procName)
            : event(evt), isScheduled(false) {
            pCtx = pContext;
            siteShortName = pContext->GetSiteShortName(evt.siteId);

            configParameters = pCtx->GetJobConfigurationParameters(evt.jobId, S4S_YIELD_FEAT_CFG_PREFIX);
            parameters = QJsonDocument::fromJson(evt.parametersJson.toUtf8()).object();
            procShortName = procName;

            startDate = ProcessorHandlerHelper::GetDateTimeFromString(
                        ProcessorHandlerHelper::GetStringConfigValue(parameters, configParameters, "start_date", S4S_YIELD_FEAT_CFG_PREFIX));
            endDate = ProcessorHandlerHelper::GetDateTimeFromString(
                        ProcessorHandlerHelper::GetStringConfigValue(parameters, configParameters, "end_date", S4S_YIELD_FEAT_CFG_PREFIX));

            const QDate &dt = startDate.date();
            year = startDate.date().year();           // TODO: see if this is valid

            const SeasonList &seasons = pContext->GetSiteSeasons(evt.siteId);
            for (const Season &s: seasons) {
                if (dt >= s.startDate && dt < s.endDate.addDays(1)) {
                    season = s;
                    break;
                }
            }
            if (season.name.size() == 0) {
                pCtx->MarkJobFailed(event.jobId);
                throw std::runtime_error(QStringLiteral("Yield Features: No valid season found for site %1 and interval %2 - %3.")
                                         .arg(siteShortName)
                                         .arg(startDate.toString())
                                         .arg(endDate.toString()).toStdString());
            }

            enableSafy = ProcessorHandlerHelper::GetBoolConfigValue(parameters, configParameters,
                                    "enable_safy", S4S_YIELD_FEAT_CFG_PREFIX, true);

            suPath = ProcessorHandlerHelper::GetStringConfigValue(parameters, configParameters, "su_path", S4S_YIELD_FEAT_CFG_PREFIX);
            suPath = suPath.replace("{site}", siteShortName);
            suPath = GetSUShapefile(suPath);
            suUniqueId = "ID_2";    // TODO: This should be configurable

            const ProductList &weatherPrdsList = pCtx->GetProducts(event.siteId, (int)ProductType::ERA5WeatherProductTypeId,
                                                                               startDate, endDate.addDays(1));
            if (weatherPrdsList.size() == 0) {
                pCtx->MarkJobFailed(event.jobId);
                throw std::runtime_error(QStringLiteral("Yield: No weather products were found in database for site %1 and interval %2 - %3.")
                                         .arg(siteShortName)
                                         .arg(startDate.toString())
                                         .arg(endDate.toString()).toStdString());
            }
            SetWeatherProducts(weatherPrdsList);

            // extract the historical yield file
            historicalYieldFile = GetSUHistoricalFile();
        }

        void SetWeatherProducts(const ProductList &weatherPrds) {
            weatherPrdPaths.reserve(weatherPrds.size());
            for (auto const &prd : weatherPrds) weatherPrdPaths << prd.fullPath;
        }

        QString GetSUHistoricalFile() {
            const QString &histYieldFile = GetProcessorDirValue(parameters, configParameters, "historical_data_path", siteShortName,
                                                       season.name, QString::number(year), S4S_YIELD_SU_DEF_HIST_DATA_PATH);
            QFileInfo qfi(histYieldFile);
            if (!qfi.exists() || !qfi.isFile()) {
                Logger::info(QStringLiteral("Yield: Historical Yield file for site %1 was not uploaded yet. The parcel trends will not be computed!")
                                         .arg(siteShortName));
                return "";
            }
            return histYieldFile;
        }

        QString GetSUShapefile(const QString &suDir) {
            QDir directory(suDir);
            const QStringList &dirFiles = directory.entryList(QStringList() << "*.shp" ,QDir::Files);
            foreach(const QString &fileName, dirFiles) {
                return directory.filePath(fileName);
            }
            Logger::info(QStringLiteral("Yield: SU geometries file for site %1 was not uploaded yet. The parcel trends and statistics at SU level will not be computed!")
                                     .arg(siteShortName));
            return "";
        }


        QString GetProcessorDirValue(const QJsonObject &parameters, const std::map<QString, QString> &configParameters,
                                     const QString &key, const QString &siteShortName, const QString &seasonName, const QString &year, const QString &defVal = "") const;

        EventProcessingContext *pCtx;
        JobSubmittedEvent event;

        QString siteShortName;
        Season season;
        QDateTime startDate;
        QDateTime endDate;
        QStringList weatherPrdPaths;

        std::map<QString, QString> configParameters;
        QJsonObject parameters;
        bool isScheduled;
        int year;
        bool enableSafy;
        QString historicalYieldFile;
        QString procShortName;

        QString suPath;
        QString suUniqueId;

    } S4SYieldJobConfig;

private:
    void HandleJobSubmittedImpl(EventProcessingContext &ctx,
                                const JobSubmittedEvent &event) override;
    void HandleTaskFinishedImpl(EventProcessingContext &ctx,
                                const TaskFinishedEvent &event) override;

    ProcessorJobDefinitionParams GetProcessingDefinitionImpl(SchedulingContext &ctx, int siteId, int scheduledDate,
                                                const ConfigurationParameterValueMap &requestOverrideCfgValues) override;
    QList<std::reference_wrapper<TaskToSubmit>> CreateTasks(const S4SYieldJobConfig &cfg, QList<TaskToSubmit> &outAllTasksList,
                                                            const S4CMarkersDB1DataExtractStepsBuilder &dataExtrStepsBuilder);
    NewStepList CreateSteps(QList<TaskToSubmit> &allTasksList,
                            const S4SYieldJobConfig &cfg, const S4CMarkersDB1DataExtractStepsBuilder &dataExtrStepsBuilder);
    int CreateMergeTasks(QList<TaskToSubmit> &outAllTasksList, const QString &taskName, int minPrdDataExtrIndex, int maxPrdDataExtrIndex, int &curTaskIdx);
    QString CreateStepsForFilesMerge(const S4SYieldJobConfig &jobCfg, const QStringList &dataExtrDirs,
                                     NewStepList &steps, QList<TaskToSubmit> &allTasksList, int &curTaskIdx);

    QStringList GetSGLaiTaskArgs(int year, const QString &mdb1File, const QString &sgOutFile,
                                 const QString &outCropGrowthIndicesFile, const QString &outLaiMetricsFile);
    QStringList GetParcelsExtractionTaskArgs(int siteId, int year, const QString &outFile, const QString &parcelFeaturesCsv);
    QStringList GetTrendFeaturesTaskArgs(const QString &input, int year, const QString &output);
    QStringList GetParcelToSUTaskArgs(int siteId, int seasonId, const QString &suPathFile, const QString &output);
    QStringList GetParcelTrendsTaskArgs(const QString &trendFeaturesPath, const QString &parcelInfosFile, const QString &parcelToSUFile, const QString &output);

    QStringList GetWeatherFeaturesTaskArgs(const QStringList &weatherFiles, const QString &parcelsShp, const QString &outDir,
                                                            const QString &outGridToParcels, const QString &outParcelToGrid);
    QStringList GetWeatherFeaturesMergeTaskArgs(const QString &inDir, const QString &outWeatherFeatures);

    QStringList GetSafyLutTaskArgs(const QStringList &weatherFiles, const QString &safyParamFile,
                                   const QString &safyParamsRangesDir, const QString &outLutDir);
    QStringList GetMergeLaiGridTaskArgs(const QString &inputLaiFile, const QString &parcelsToGridFile, const QString &outMergedFile);
    QStringList GetSafyOptimTaskArgs(const QStringList &weatherFiles,  int year, const QString &inputLaiFile, const QString &gridToParcelsFile,
                                     const QString &safyParamsFile, const QString &safyParamsRangesFile,
                                     const QString &lutDir, const QString &workingDir, const QString &outSafyOptimFile);
    QStringList GetAllFeaturesMergeTaskArgs(const QString &weatherFeatFile, const QString &sgCropGrowthIndicesFile,
                                            const QString &safyFeatsFile, const QString &outMergedFeatures, const QString &sgYieldLaiFeaturesPath, const QString &parcelFeaturesCsv, const QString &parcelTrendFeaturesPath);
    QStringList GetYieldFeaturesTaskArgs(const QString &inMergedFeatures, const QString &outYieldFeatures);

    QStringList GetProductFormatterArgs(TaskToSubmit &productFormatterTask, const S4SYieldJobConfig &cfg, const QStringList &listFiles);
};

