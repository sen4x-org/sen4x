#pragma once

#include "processorhandler.hpp"
#include "optional.hpp"
#include "../s4c_mdb1_dataextract_steps_builder.hpp"
#include "../products/generichighlevelproducthelper.h"
#include "s4s_yield_common.h"

#define ESU_EXTRACTION_TASK_NAME QStringLiteral("yield-esu-extraction")
#define S4S_YIELD_SU_DEF_DATA_EXTR_ROOT   "/mnt/archive/marker_database_files/yield_su/mdb1/{site}/{year}/data_extraction/"

class S4SYieldSUFeaturesHandler : public ProcessorHandler
{
    typedef struct S4SYieldJobConfig {
        S4SYieldJobConfig(EventProcessingContext *pContext, const JobSubmittedEvent &evt, const QString &procShortName)
            : event(evt), isScheduled(false) {
            pCtx = pContext;
            siteShortName = pContext->GetSiteShortName(evt.siteId);
            configParameters = pCtx->GetJobConfigurationParameters(evt.jobId, S4S_YIELD_FEAT_CFG_PREFIX);
            parameters = QJsonDocument::fromJson(evt.parametersJson.toUtf8()).object();

            startDate = ProcessorHandlerHelper::GetDateTimeFromString(
                        ProcessorHandlerHelper::GetStringConfigValue(parameters, configParameters, "start_date", S4S_YIELD_FEAT_CFG_PREFIX));
            endDate = ProcessorHandlerHelper::GetDateTimeFromString(
                        ProcessorHandlerHelper::GetStringConfigValue(parameters, configParameters, "end_date", S4S_YIELD_FEAT_CFG_PREFIX));

            for(int year = startDate.date().year(); year <= endDate.date().year(); year++) {
                if (std::find(years.begin(), years.end(), year) == years.end()) {
                    years.push_back(year);
                }
            }

            // extract the historical yield file
            historicalYieldFile = GetProcessorDirValue(parameters, configParameters, "historical_data_path", siteShortName,
                                                       procShortName, S4S_YIELD_SU_DEF_HIST_DATA_PATH);
            QFileInfo qfi(historicalYieldFile);
            if (!qfi.exists() || !qfi.isFile()) {
                pCtx->MarkJobFailed(event.jobId);
                throw std::runtime_error(QStringLiteral("Yield SU: Historical Yield file for site %1 was not uploaded yet!")
                                         .arg(siteShortName).toStdString());
            }

            dataExtractionRootDir = ProcessorHandlerHelper::GetStringConfigValue(parameters, configParameters, "data_extr_dir", S4S_YIELD_FEAT_CFG_PREFIX);
            if (dataExtractionRootDir.size() == 0) {
                dataExtractionRootDir = S4S_YIELD_SU_DEF_DATA_EXTR_ROOT;
            }
            suPath = ProcessorHandlerHelper::GetStringConfigValue(parameters, configParameters, "su_path", S4S_YIELD_FEAT_CFG_PREFIX);
            suPath = suPath.replace("{site}", siteShortName);
            suPath = GetSUShapefile(suPath);
            suUniqueId = "ID_2";    // TODO: This should be configurable
            cropTypePrds = GetCropTypeProducts();

            // Check the years from the given interval and the years where the crop types are available
            QList<int> ctYears;
            ctYears.reserve(cropTypePrds.size());
            for (const Product& prd : cropTypePrds) {
                ctYears.append(prd.created.date().year());
            }
            // bool identical = QSet<int>(list1.begin(), list1.end()) == QSet<int>(list2.begin(), list2.end());
            bool allYearsHaveCT = true;
            if (ctYears.size() != (int)years.size()) {
                allYearsHaveCT = false;
            } else {
                QSet<int> setYears;
                setYears.reserve(years.size());
                for (int y : years) {
                    setYears.insert(y);
                }
                for (int ctYear : ctYears) {
                    if (!setYears.contains(ctYear)) {
                        allYearsHaveCT = false;
                        break;
                    }
                }
            }
            if (!allYearsHaveCT) {
                pCtx->MarkJobFailed(event.jobId);
                throw std::runtime_error(QStringLiteral("Yield SU Feature: Not all years selected for site %1 and interval %2 - %3 have a crop type.")
                                         .arg(siteShortName)
                                         .arg(startDate.toString())
                                         .arg(endDate.toString()).toStdString());
            }
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
            lpisInfos = CreateLpisInfos(procShortName);
        }

        void SetWeatherProducts(const ProductList &weatherPrds) {
            weatherPrdPaths.reserve(weatherPrds.size());
            for (auto const &prd : weatherPrds) weatherPrdPaths << prd.fullPath;
        }

        QString GetSUShapefile(const QString &suDir) {
            QDir directory(suDir);
            const QStringList &dirFiles = directory.entryList(QStringList() << "*.shp" ,QDir::Files);
            foreach(const QString &fileName, dirFiles) {
                return directory.filePath(fileName);
            }
            pCtx->MarkJobFailed(event.jobId);
            throw std::runtime_error(
                QStringLiteral("Yield SU: Unable to find a shapefile in directory %1").arg(suDir).toStdString());
        }

        QMap<int, LpisInfos> CreateLpisInfos(const QString &procShortName)
        {
            const QString &jobPath = pCtx->GetJobOutputPath(event.jobId, procShortName);
            const QString &rastersPath = QDir(jobPath).filePath("0000" + ESU_EXTRACTION_TASK_NAME + "-lpis-rasters");
            if (!QDir::root().mkpath(rastersPath)) {
                pCtx->MarkJobFailed(event.jobId);
                throw std::runtime_error(
                    QStringLiteral("Unable to create job output path %1").arg(rastersPath).toStdString());
            }

            siteTiles = pCtx->GetSiteTiles(event.siteId, (int)Satellite::Sentinel2);

            int startYear = startDate.date().year();
            int endYear = endDate.date().year();
            for (int i = 0; i <= (endYear - startYear); i++) {
                int curYear = startYear+i;
                QMap<QString, QString> esuTileRasters;
                for (const Tile &tile : siteTiles) {
                    esuTileRasters[tile.tileId] = QDir(rastersPath).filePath("ESU_Random_" + tile.tileId + "_" + QString::number(curYear) + ".tif");
                }

                esuRasterPaths[curYear] = esuTileRasters;

                LpisInfos infos;
                infos.productDate = startDate.addYears(i);
                infos.insertedDate = infos.productDate;
                infos.productName = QStringLiteral("LPIS_") + QString::number(curYear);
                infos.optTilesGeomsRasters = esuTileRasters;
                infos.sarTilesGeomsRasters = esuTileRasters;
                lpisInfos[curYear] = infos;
            }

            return lpisInfos;
        }

        ProductList GetCropTypeProducts();
        QString GetProcessorDirValue(const QJsonObject &parameters, const std::map<QString, QString> &configParameters,
                                     const QString &key, const QString &siteShortName, const QString &procShortName, const QString &defVal );

        EventProcessingContext *pCtx;
        JobSubmittedEvent event;

        QString siteShortName;
        QDateTime startDate;
        QDateTime endDate;
        QStringList filterProductNames;
        QStringList weatherPrdPaths;
        // bool enableYieldModel;
        // QString yieldFeatPrd;
        // bool extractFeatures;

        std::map<QString, QString> configParameters;
        QJsonObject parameters;
        bool isScheduled;
        std::vector<int> years;
        QMap<int, LpisInfos> lpisInfos;
        ProductList cropTypePrds;
        QString dataExtractionRootDir;
        QString suPath;
        QString suUniqueId;
        QMap<int, QMap<QString, QString>> esuRasterPaths;
        TileList siteTiles;
        QString historicalYieldFile;

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

    QStringList GetEsuExtractionTaskArgs(const S4SYieldJobConfig &cfg, const QString &workingDir, const QString &outESUCsvFile,
                                         const QString &outSUAdditionalInfoCsvFile, const QString &ctPath, int ctYear);
    QStringList GetESUAggregationTaskArgs(const QStringList &esuCsvFiles, const QList<int> &ctYears, const QString &laiMergedPath, const QString &workingDir,
                                          const QString &outAggregatedLAI);
    QStringList GetSGLaiTaskArgs(const std::vector<int> &years, const QString &mdb1File, const QString &sgOutFile,
                                 const QString &outCropGrowthIndicesFile, const QString &outLaiMetricsFile);
    QStringList GetTrendFeaturesTaskArgs(const QString &input, const std::vector<int> &years, const QString &output);
    QStringList GetParcelsExtractionTaskArgs(int siteId, int year, const QString &outFile);
    QStringList GetWeatherFeaturesTaskArgs(const QStringList &weatherFiles, const QString &parcelsShp, const QString &shpIdFieldName, const QString &outDir);
    QStringList GetWeatherFeaturesMergeTaskArgs(const QString &inDir, const QString &outWeatherFeatures);

    QStringList GetAllFeaturesMergeTaskArgs(const QString &sgListFile, const QString &trendFeatFile, const QString &weatherFeatFile,
                                            const QString &outMergedFeatures, const QString &sgYieldLaiFeaturesPath,
                                            const QString &suAdditionalInfosPath);
    QStringList GetYieldFeaturesTaskArgs(const QString &inMergedFeatures, int maxYear, const QString &outYieldFeatures, const QString &outPrevYearsYieldFeatures);
    QStringList GetMergeYieldFeaturesTaskArgs(const QString &inYieldFeatures, const QString &outMergedYieldFeatures);

    QString GetProcessorDirValue(const QJsonObject &parameters, const std::map<QString, QString> &configParameters,
                                 const QString &key, const QString &siteShortName, const QString &defVal = "");
    QStringList GetProductFormatterArgs(TaskToSubmit &productFormatterTask, const S4SYieldJobConfig &cfg, const QStringList &listFiles);
};

