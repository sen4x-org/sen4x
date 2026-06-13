#ifndef LAIRETRIEVALHANDLERL3BINDIVIDUAL_HPP
#define LAIRETRIEVALHANDLERL3BINDIVIDUAL_HPP

#include "processorhandler.hpp"

#define L3B_CFG_PREFIX   "processor.l3b."



class LaiRetrievalHandlerL3BIndividual : public ProcessorHandler
{
public:
    typedef struct {

        QString productMetadataFile;
        QString tileId;
        QString prdExternalMskFile;
        Product parentProductInfo;
    } ProductInfo;

    typedef struct {
        QString tileId;
        QString productMetadataFile;
        QString inPrdExtMsk;

        QString resultFile;

        QString statusFlagsFile;
        QString statusFlagsFileResampled;
        QString inDomainFlagsFile;
        QString biDomainFlagsFile;

        QString anglesFile;
    } ResultFileInfo;

    typedef struct {
        QString name;
        bool isBI;
        QString category;       // Spectral indicator category (Vegetation, Soil, etc.)
        QString paramName;
        ProductType prdType;
    } IndicatorDescription;

    class L3BJobContext {
        public:
            L3BJobContext(LaiRetrievalHandlerL3BIndividual *parent, EventProcessingContext *pContext, const JobSubmittedEvent &evt) :
                event(evt) {

                QString procPrefix("processor." + parent->processorDescr.shortName + ".");
                pCtx = pContext;
                parameters = QJsonDocument::fromJson(evt.parametersJson.toUtf8()).object();
                configParameters = pCtx->GetJobConfigurationParameters(evt.jobId, L3B_CFG_PREFIX);
                // siteShortName = pContext->GetSiteShortName(evt.siteId);
                laiCfgFile = configParameters[procPrefix + "lai.laibandscfgfile"];
                for (const IndicatorDescription &indexDescr: indicatorsDescriptions.values()) {
                    if (ProcessorHandlerHelper::GetBoolConfigValue(parameters, configParameters, "filter.produce_" + indexDescr.name, procPrefix)) {
                        if (indexDescr.prdType != ProductType::InvalidProductTypeId) {
                            indicesToCompute.append(indexDescr);
                        }
                    }
                }
                bGenInDomainFlags = ProcessorHandlerHelper::GetBoolConfigValue(parameters, configParameters, "filter.produce_in_domain_flags", procPrefix);
                bGenMosaic = ProcessorHandlerHelper::GetBoolConfigValue(parameters, configParameters, "produce_mosaic", procPrefix);
                bChainInputsSteps = ProcessorHandlerHelper::GetBoolConfigValue(parameters, configParameters, "filter.chain_inputs_steps", procPrefix);

                int resolution = 0;
                if(!ProcessorHandlerHelper::GetParameterValueAsInt(parameters, "resolution", resolution) ||
                        resolution == 0) {
                    resolution = 10;    // TODO: We should configure the default resolution in DB
                }
                resolutionStr = QString::number(resolution);

                bRemoveTempFiles = parent->NeedRemoveJobFolder(*pCtx, event.jobId, parent->processorDescr.shortName);

                lutFile = ProcessorHandlerHelper::GetMapValue(configParameters, procPrefix + "lai.lut_path");
            }

            EventProcessingContext *pCtx;
            JobSubmittedEvent event;
            QJsonObject parameters;
            std::map<QString, QString> configParameters;

            QList<IndicatorDescription> indicesToCompute;
            QString laiCfgFile;
            bool bGenInDomainFlags;
// TODO: See if is needed such limitation
//            bool bGenOutDomainFlags;
            bool bGenMosaic;
            QString resolutionStr;
            bool bRemoveTempFiles;
            QString lutFile;
            bool bChainInputsSteps;

            static QMap<QString, IndicatorDescription> indicatorsDescriptions;
    };


private:

    void HandleJobSubmittedImpl(EventProcessingContext &ctx,
                                const JobSubmittedEvent &evt) override;
    void HandleTaskFinishedImpl(EventProcessingContext &ctx,
                                const TaskFinishedEvent &event) override;

    void CreateTasksForNewProduct(const L3BJobContext &jobCtx, const IndicatorDescription & indexDescr, QList<TaskToSubmit> &outAllTasksList);
    int CreateAnglesTasks(int parentTaskId, QList<TaskToSubmit> &outAllTasksList, int nCurTaskIdx, int & nAnglesTaskId);
    int CreateSpectralIndicatorTasks(int parentTaskId, QList<TaskToSubmit> &outAllTasksList,
                                         QList<std::reference_wrapper<const TaskToSubmit>> &productFormatterParentsRefs,
                                         int nCurTaskIdx);
    int CreateNdviVegStatsTasks(int parentTaskId, QList<TaskToSubmit> &outAllTasksList,
                                QList<std::reference_wrapper<const TaskToSubmit>> &productFormatterParentsRefs,
                                int nCurTaskIdx);
    int CreateBiophysicalIndicatorTasks(int parentTaskId, QList<TaskToSubmit> &outAllTasksList,
                                         QList<std::reference_wrapper<const TaskToSubmit>> &productFormatterParentsRefs,
                                         int nCurTaskIdx);

    void GetModelFileList(const QString &folderName, const QString &modelPrefix, QStringList &outModelsList);
    void WriteExecutionInfosFile(const QString &executionInfosPath, const ResultFileInfo &resultFiles);
    void WriteInputPrdIdFile(const QString &outFilePath, const ProductInfo &prdInfo);

    QStringList GetCreateAnglesArgs(const QString &inputProduct, const QString &anglesFile);
    QStringList GetGdalTranslateAnglesNoDataArgs(const QString &anglesFile, const QString &resultAnglesFile);
    QStringList GetGdalBuildAnglesVrtArgs(const QString &anglesFile, const QString &resultVrtFile);
    QStringList GetGdalTranslateResampleAnglesArgs(const QString &vrtFile, const QString &resultResampledAnglesFile);
    QStringList GetGenerateInputDomainFlagsArgs(const QString &xmlFile,  const QString &laiBandsCfg,
                                                const QString &outFlagsFileName, const QString &outRes);
    QStringList GetGenerateOutputDomainFlagsArgs(const QString &xmlFile, const QString &laiRasterFile,
                                                const QString &laiBandsCfg, const QString &indexName, const QString &extMsk,
                                                const QString &outFlagsFileName,  const QString &outCorrectedLaiFile, const QString &outRes);

    QStringList GetSpectralIndicatorsExtractionArgs(const QString &inputProduct, const QString &indicator, const QString &msksFlagsFile,
                                            const QString &indicatorFile);
    QStringList GetLaiProcessorArgs(const QString &xmlFile, const QString &anglesFileName, const QString &resolution,
                                    const QString &laiBandsCfg, const QString &monoDateLaiFileName, const QString &indexName);
    QStringList GetQuantifyImageArgs(const QString &inFileName, const QString &outFileName);
    QStringList GetMonoDateMskFlagsArgs(const QString &inputProduct, const QString &extMsk, const QString &monoDateMskFlgsFileName, const QString &monoDateMskFlgsResFileName, const QString &resStr);
    QStringList GetProductFormatterArgs(TaskToSubmit &productFormatterTask, const L3BJobContext &jobCtx, const ProductInfo &prdInfo, const IndicatorDescription &indexDescr, const ResultFileInfo &resultFilesInfo);
    QStringList GetCompositeDuplicateDatesArgs(const QString &outCompositeFile);
    NewStepList GetStepsForNewProduct(const L3BJobContext &jobCtx,
                                       const ProductInfo &prdInfo, const IndicatorDescription &indexDescr, QList<TaskToSubmit> &allTasksList, int tasksStartIdx);
    int GetStepsForStatusFlags(const L3BJobContext &jobCtx, QList<TaskToSubmit> &allTasksList, int curTaskIdx,
                                ResultFileInfo &tileResultFileInfo, NewStepList &steps, QStringList &cleanupTemporaryFilesList);
    int GetStepsForSpectralIndicator(QList<TaskToSubmit> &allTasksList, const QString &indexName, int curTaskIdx,
                                ResultFileInfo &tileResultFileInfo, NewStepList &steps, QStringList &cleanupTemporaryFilesList);
//    int GetStepsForNdviVegStats(const L3BJobContext &jobCtx, QList<TaskToSubmit> &allTasksList, int curTaskIdx, const ProductInfo &prdInfo,
//                                ResultFileInfo &tileResultFileInfo,  NewStepList &steps);
    int GetStepsForAnglesCreation(QList<TaskToSubmit> &allTasksList, int curTaskIdx, ResultFileInfo &tileResultFileInfo, NewStepList &steps, QStringList &cleanupTemporaryFilesList);
    int GetStepsForMonoDateBI(const L3BJobContext &jobCtx, QList<TaskToSubmit> &allTasksList, int curTaskIdx, const QString &indexName, ResultFileInfo &tileResultFileInfo,
                              NewStepList &steps, QStringList &cleanupTemporaryFilesList);
    int GetStepsForInDomainFlags(const L3BJobContext &jobCtx, QList<TaskToSubmit> &allTasksList, int curTaskIdx, ResultFileInfo &tileResultFileInfo, NewStepList &steps,
                                QStringList &cleanupTemporaryFilesList);

    const QString& GetDefaultCfgVal(std::map<QString, QString> &configParameters, const QString &key, const QString &defVal);

    ProcessorJobDefinitionParams GetProcessingDefinitionImpl(SchedulingContext &ctx, int siteId, int scheduledDate,
                                                const ConfigurationParameterValueMap &requestOverrideCfgValues) override;
    QSet<QString> GetTilesFilter(const L3BJobContext &jobCtx);
    bool FilterTile(const QSet<QString> &tilesSet, const ProductDetails &prdDetails);
    void InitTileResultFiles(const ProductInfo &tileInfo, ResultFileInfo &tileResultFileInfo);

    void HandleProduct(const L3BJobContext &jobCtx, const IndicatorDescription &indexName, const ProductInfo &prdInfo, QList<TaskToSubmit> &allTasksList);
    void SubmitEndOfLaiTask(EventProcessingContext &ctx, const JobSubmittedEvent &event,
                            const QList<TaskToSubmit> &allTasksList);

private:
    int UpdateJobSubmittedParamsFromSchedReq(const L3BJobContext &jobCtx, const IndicatorDescription &indexDescr, ProductList &prdsToProcess);
    ProductList GetL2AProductsNotProcessedProductProvenance(const L3BJobContext &jobCtx, const IndicatorDescription &indexDescr,
                                                            const QDateTime &startDate, const QDateTime &endDate);
    QString GetSiteCurrentProcessingPrdsFile(EventProcessingContext &ctx, int jobId, int siteId, const QString &indexName);
    void SaveTaskIndicator(TaskToSubmit &task, const QString &indicatorName);
    IndicatorDescription GetTaskSavedIndicator(EventProcessingContext &ctx, const TaskFinishedEvent &evt);

    friend class LaiRetrievalHandler;
    friend class L3BJobContext;
};

#endif // LAIRETRIEVALHANDLERL3BINDIVIDUAL_HPP

