#include <QJsonDocument>
#include <QJsonObject>
#include <QRegularExpression>

#include <fstream>

#include "lairetrievalhandler_l3b_individual.hpp"
#include "processorhandlerhelper.h"
#include "json_conversions.hpp"
#include "logger.hpp"
#include "maccshdrmeananglesreader.hpp"
#include <unordered_map>

#include <QHash>
#include <QString>
#include <functional>

#include "products/generichighlevelproducthelper.h"
#include "processor/products/producthelper.h"
#include "processor/products/producthelperfactory.h"
using namespace orchestrator::products;

#if QT_VERSION < QT_VERSION_CHECK(5, 14, 0)
// For unordered map and QString as key
namespace std {
  template<> struct hash<QString> {
    std::size_t operator()(const QString& s) const noexcept {
      return (size_t) qHash(s);
    }
  };
}
#endif

#define CURRENT_PROC_PRDS_FILE_NAME     "current_processing_l3b_%1.txt"
#define INDICATOR_NAME_FILE     "indicator_name.txt"


QMap<QString, LaiRetrievalHandlerL3BIndividual::IndicatorDescription>
    LaiRetrievalHandlerL3BIndividual::L3BJobContext::indicatorsDescriptions = {
     {"ndvi", {"ndvi", false, "Vegetation", "NDVI", ProductType::L3BNdviProductTypeId}},
     {"tndvi", {"tndvi", false, "Vegetation", "TNDVI", ProductType::InvalidProductTypeId}},
     {"rdvi", {"rdvi", false, "Vegetation", "RVI", ProductType::InvalidProductTypeId}},
     {"savi", {"savi", false, "Vegetation", "SAVI", ProductType::InvalidProductTypeId}},
     {"tsavi", {"tsavi", false, "Vegetation", "TSAVI", ProductType::InvalidProductTypeId}},
     {"msavi", {"msavi", false, "Vegetation", "MSAVI", ProductType::InvalidProductTypeId}},
     {"msavi2", {"msavi2", false, "Vegetation", "MSAVI2", ProductType::InvalidProductTypeId}},
     {"gemi", {"gemi", false, "Vegetation", "GEMI", ProductType::InvalidProductTypeId}},
     {"ipvi", {"ipvi", false, "Vegetation", "IPVI", ProductType::InvalidProductTypeId}},
     {"laindvilog", {"laindvilog", false, "Vegetation", "LAIFromNDVILog", ProductType::InvalidProductTypeId}},
     {"lairefl", {"lairefl", false, "Vegetation", "LAIFromReflLinear", ProductType::InvalidProductTypeId}},
     {"ndwi", {"ndwi", false, "Water", "NDWI", ProductType::L3BNdwiProductTypeId}},
     {"ndwi2", {"ndwi2", false, "Water", "NDWI2", ProductType::InvalidProductTypeId}},
     {"mndwi", {"mndwi", false, "Water", "MNDWI", ProductType::InvalidProductTypeId}},
     {"ndti", {"ndti", false, "Water", "NDTI", ProductType::InvalidProductTypeId}},
     {"redness", {"redness", false, "Soil", "RI", ProductType::InvalidProductTypeId}},
     {"colorindex",{"colorindex", false, "Soil", "CI", ProductType::InvalidProductTypeId}},
     {"brightness", {"brightness", false, "Soil", "BI", ProductType::L3BBrightnessProductTypeId}},
     {"brightness2", {"brightness2", false, "Soil", "BI2", ProductType::InvalidProductTypeId}},
     {"lai", {"lai", true, "Biophysical", "LAI", ProductType::L3BLaiProductTypeId}},
     {"fapar", {"fapar", true, "Biophysical", "FAPAR", ProductType::L3BFaparProductTypeId}},
     {"fcover", {"fcover", true, "Biophysical", "FCOVER", ProductType::L3BFcoverProductTypeId}}

};

void LaiRetrievalHandlerL3BIndividual::CreateTasksForNewProduct(const L3BJobContext &jobCtx, const IndicatorDescription & indexDescr,
                                                         QList<TaskToSubmit> &outAllTasksList) {

    // in allTasksList we might have tasks from other products. We start from the first task of the current product
    int initialTasksNo = outAllTasksList.size();
    outAllTasksList.append(TaskToSubmit{"lai-processor-mask-flags", {}});
    if (indexDescr.isBI) {
        outAllTasksList.append(TaskToSubmit{"lai-create-angles", {}});
        outAllTasksList.append(TaskToSubmit{"gdal_translate", {}});
        outAllTasksList.append(TaskToSubmit{"gdalbuildvrt", {}});
        outAllTasksList.append(TaskToSubmit{"gdal_translate", {}});
        outAllTasksList.append(TaskToSubmit{indexDescr.name + "-processor", {}});
        outAllTasksList.append(TaskToSubmit{indexDescr.name + "-quantify-image", {}});
        outAllTasksList.append(TaskToSubmit{indexDescr.name + "gen-domain-flags", {}});
    } else {
        // spectral indices
        outAllTasksList.append(TaskToSubmit{"lai-processor-" + indexDescr.name + "-extractor", {}});

    }
    if (jobCtx.bGenInDomainFlags) {
        // add the task for generating domain input flags
        outAllTasksList.append(TaskToSubmit{"gen-domain-flags", {}});
    }
    outAllTasksList.append(TaskToSubmit{"product-formatter", {}});
    outAllTasksList.append(TaskToSubmit{"l3b-composite-duplicate-dates", {}});
    if(jobCtx.bRemoveTempFiles) {
        outAllTasksList.append(TaskToSubmit{ "files-remover", {} });
    }

    QList<std::reference_wrapper<const TaskToSubmit>> productFormatterParentsRefs;
    int nCurTaskIdx = initialTasksNo;

    // if we want chaining products and we have a previous product executed
    if(jobCtx.bChainInputsSteps && initialTasksNo > 0) {
        // we create a dependency to the last task of the previous product
        outAllTasksList[nCurTaskIdx].parentTasks.append(outAllTasksList[nCurTaskIdx-1]);
    }   // else  skip over the lai-processor-mask-flags as we run it with no previous dependency,
        // allowing running several products in parallel
    // increment the current index for ndvi-rvi-extraction
    nCurTaskIdx++;

    // lai-processor-ndvi-extraction, lai-processor, fapar-processor, fcover-processor -> lai-processor-mask-flags
    // all these are run in parallel
    int flagsTaskIdx = nCurTaskIdx-1;
    int nAnglesTaskId = flagsTaskIdx;
    if (indexDescr.isBI) {
        nCurTaskIdx = CreateAnglesTasks(flagsTaskIdx, outAllTasksList, nCurTaskIdx, nAnglesTaskId);
        nCurTaskIdx = CreateBiophysicalIndicatorTasks(nAnglesTaskId, outAllTasksList, productFormatterParentsRefs, nCurTaskIdx);
    } else {
        nCurTaskIdx = CreateSpectralIndicatorTasks(flagsTaskIdx, outAllTasksList, productFormatterParentsRefs, nCurTaskIdx);
    }
    if (jobCtx.bGenInDomainFlags) {
        int nInputDomainIdx = nCurTaskIdx++;
        outAllTasksList[nInputDomainIdx].parentTasks.append(outAllTasksList[flagsTaskIdx]);
        // add the input domain task to the list of the product formatter corresponding to this product
        productFormatterParentsRefs.append(outAllTasksList[nInputDomainIdx]);
    }
    int productFormatterIdx = nCurTaskIdx++;
    outAllTasksList[productFormatterIdx].parentTasks.append(productFormatterParentsRefs);

    int compositeDuplicatedDates = nCurTaskIdx++;
    outAllTasksList[compositeDuplicatedDates].parentTasks.append(outAllTasksList[productFormatterIdx]);

    if(jobCtx.bRemoveTempFiles) {
        // cleanup-intermediate-files -> product formatter
        outAllTasksList[nCurTaskIdx].parentTasks.append(outAllTasksList[compositeDuplicatedDates]);
    }
}

int LaiRetrievalHandlerL3BIndividual::CreateAnglesTasks(int parentTaskId, QList<TaskToSubmit> &outAllTasksList,
                                     int nCurTaskIdx, int & nAnglesTaskId)
{
    int createAnglesIdx = nCurTaskIdx++;
    outAllTasksList[createAnglesIdx].parentTasks.append(outAllTasksList[parentTaskId]);
    int anglesGdalTranslateNoDataIdx = nCurTaskIdx++;
    outAllTasksList[anglesGdalTranslateNoDataIdx].parentTasks.append(outAllTasksList[createAnglesIdx]);
    int gdalBuildVrtIdx = nCurTaskIdx++;
    outAllTasksList[gdalBuildVrtIdx].parentTasks.append(outAllTasksList[anglesGdalTranslateNoDataIdx]);
    int anglesResamleIdx = nCurTaskIdx++;
    outAllTasksList[anglesResamleIdx].parentTasks.append(outAllTasksList[gdalBuildVrtIdx]);
    nAnglesTaskId = anglesResamleIdx;

    return nCurTaskIdx;
}

int LaiRetrievalHandlerL3BIndividual::CreateSpectralIndicatorTasks(int parentTaskId, QList<TaskToSubmit> &outAllTasksList,
                                     QList<std::reference_wrapper<const TaskToSubmit>> &productFormatterParentsRefs,
                                     int nCurTaskIdx) {
    int spectralIndExtrIdx = nCurTaskIdx++;
    outAllTasksList[spectralIndExtrIdx].parentTasks.append(outAllTasksList[parentTaskId]);
    // add the spectral indicator task to the list of the product formatter corresponding to this product
    productFormatterParentsRefs.append(outAllTasksList[spectralIndExtrIdx]);

    return nCurTaskIdx;
}

int LaiRetrievalHandlerL3BIndividual::CreateNdviVegStatsTasks(int parentTaskId, QList<TaskToSubmit> &outAllTasksList,
                                     QList<std::reference_wrapper<const TaskToSubmit>> &productFormatterParentsRefs,
                                     int nCurTaskIdx) {
    int vegStatsTaskIdx = nCurTaskIdx++;
    outAllTasksList[vegStatsTaskIdx].parentTasks.append(outAllTasksList[parentTaskId]);
    // add the spectral indicator task to the list of the product formatter corresponding to this product
    productFormatterParentsRefs.append(outAllTasksList[vegStatsTaskIdx]);

    return nCurTaskIdx;
}

int LaiRetrievalHandlerL3BIndividual::CreateBiophysicalIndicatorTasks(int parentTaskId, QList<TaskToSubmit> &outAllTasksList,
                                     QList<std::reference_wrapper<const TaskToSubmit>> &productFormatterParentsRefs,
                                     int nCurTaskIdx)
{
    int nBIProcessorIdx = nCurTaskIdx++;
    outAllTasksList[nBIProcessorIdx].parentTasks.append(outAllTasksList[parentTaskId]);

    // domain-flags-image -> BI-processor
    int nBIDomainFlagsImageIdx = nCurTaskIdx++;
    outAllTasksList[nBIDomainFlagsImageIdx].parentTasks.append(outAllTasksList[nBIProcessorIdx]);

    // TODO: We should add here an option to avoid creation of these flags
    // BI-quantify-image -> domain-flags-image
    int nBIQuantifyImageIdx = nCurTaskIdx++;
    outAllTasksList[nBIQuantifyImageIdx].parentTasks.append(outAllTasksList[nBIDomainFlagsImageIdx]);
    // add the quantified task to the list of the product formatter corresponding to this product
    productFormatterParentsRefs.append(outAllTasksList[nBIQuantifyImageIdx]);

    return nCurTaskIdx;
}

NewStepList LaiRetrievalHandlerL3BIndividual::GetStepsForNewProduct(const L3BJobContext &jobCtx, const ProductInfo &prdInfo,
                                                              const IndicatorDescription &indexDescr, QList<TaskToSubmit> &allTasksList, int tasksStartIdx)
{
    NewStepList steps;

    // in allTasksList we might have tasks from other products. We start from the first task of the current product
    int curTaskIdx = tasksStartIdx;

    QStringList cleanupTemporaryFilesList;

    ResultFileInfo resultFileInfo;
    InitTileResultFiles(prdInfo, resultFileInfo);

    curTaskIdx = GetStepsForStatusFlags(jobCtx, allTasksList, curTaskIdx, resultFileInfo, steps,
                                        cleanupTemporaryFilesList);
    if (indexDescr.isBI) {
        curTaskIdx = GetStepsForAnglesCreation(allTasksList, curTaskIdx, resultFileInfo, steps,
                                               cleanupTemporaryFilesList);
        curTaskIdx = GetStepsForMonoDateBI(jobCtx, allTasksList, curTaskIdx, indexDescr.name,
                                           resultFileInfo, steps, cleanupTemporaryFilesList);
    } else {
        curTaskIdx = GetStepsForSpectralIndicator(allTasksList, indexDescr.name, curTaskIdx, resultFileInfo,
                                     steps, cleanupTemporaryFilesList);
    }
    if (jobCtx.bGenInDomainFlags) {
        curTaskIdx = GetStepsForInDomainFlags(jobCtx, allTasksList, curTaskIdx, resultFileInfo, steps, cleanupTemporaryFilesList);
    }

    TaskToSubmit &laiMonoProductFormatterTask = allTasksList[curTaskIdx++];
    const QStringList &productFormatterArgs = GetProductFormatterArgs(laiMonoProductFormatterTask, jobCtx,
                                                                             prdInfo,  indexDescr, resultFileInfo);
    steps.append(CreateTaskStep(laiMonoProductFormatterTask, "ProductFormatter", productFormatterArgs));

    TaskToSubmit &compositeDuplicatedDatesTask = allTasksList[curTaskIdx++];
    const QString &outCompositeFile = laiMonoProductFormatterTask.GetFilePath(PRODUCT_FORMATTER_OUT_PROPS_FILE);
    const QStringList &compositeDuplicatedDatesArgs = GetCompositeDuplicateDatesArgs(outCompositeFile);
    steps.append(CreateTaskStep(compositeDuplicatedDatesTask, "CompositeDuplicatedDates", compositeDuplicatedDatesArgs));

    if(jobCtx.bRemoveTempFiles) {
        TaskToSubmit &cleanupTemporaryFilesTask = allTasksList[curTaskIdx++];
        // add also the cleanup step
        steps.append(CreateTaskStep(cleanupTemporaryFilesTask, "CleanupTemporaryFiles", cleanupTemporaryFilesList));
    }

    return steps;
}

int LaiRetrievalHandlerL3BIndividual::GetStepsForStatusFlags(const L3BJobContext &jobCtx, QList<TaskToSubmit> &allTasksList, int curTaskIdx,
                            ResultFileInfo &tileResultFileInfo, NewStepList &steps, QStringList &cleanupTemporaryFilesList) {

    TaskToSubmit &genMonoDateMskFagsTask = allTasksList[curTaskIdx++];
    tileResultFileInfo.statusFlagsFile = genMonoDateMskFagsTask.GetFilePath("LAI_mono_date_msk_flgs_img.tif");
    tileResultFileInfo.statusFlagsFileResampled = genMonoDateMskFagsTask.GetFilePath("LAI_mono_date_msk_flgs_img_resampled.tif");
    const QStringList &genMonoDateMskFagsArgs = GetMonoDateMskFlagsArgs(tileResultFileInfo.productMetadataFile,
                                                                 tileResultFileInfo.inPrdExtMsk,
                                                                 tileResultFileInfo.statusFlagsFile,
                                                                 tileResultFileInfo.statusFlagsFileResampled,
                                                                 jobCtx.resolutionStr);
    // add these steps to the steps list to be submitted
    steps.append(CreateTaskStep(genMonoDateMskFagsTask, "GenerateLaiMonoDateMaskFlags", genMonoDateMskFagsArgs));
    cleanupTemporaryFilesList.append(tileResultFileInfo.statusFlagsFile);
    cleanupTemporaryFilesList.append(tileResultFileInfo.statusFlagsFileResampled);

    return curTaskIdx;
}

int LaiRetrievalHandlerL3BIndividual::GetStepsForSpectralIndicator(QList<TaskToSubmit> &allTasksList, const QString &indexName, int curTaskIdx,
                            ResultFileInfo &tileResultFileInfo,  NewStepList &steps, QStringList &cleanupTemporaryFilesList) {

    TaskToSubmit &spectralIndicatorExtractorTask = allTasksList[curTaskIdx++];
    tileResultFileInfo.resultFile = spectralIndicatorExtractorTask.GetFilePath(indexName + ".tif");
    const QStringList &spectralIndicatorExtractionArgs = GetSpectralIndicatorsExtractionArgs(tileResultFileInfo.productMetadataFile,
                                                                 indexName, tileResultFileInfo.statusFlagsFile, tileResultFileInfo.resultFile);
    steps.append(CreateTaskStep(spectralIndicatorExtractorTask, indexName.toUpper() + "Extraction", spectralIndicatorExtractionArgs));
    // save the file to be sent to product formatter
    cleanupTemporaryFilesList.append(tileResultFileInfo.resultFile);

    return curTaskIdx;
}

//int LaiRetrievalHandlerL3BIndividual::GetStepsForNdviVegStats(const L3BJobContext &jobCtx, QList<TaskToSubmit> &allTasksList, int curTaskIdx,
//                                                       const ProductInfo &prdInfo, ResultFileInfo &tileResultFileInfo,
//                                                       NewStepList &steps) {

//    TaskToSubmit &vegStatsTask = allTasksList[curTaskIdx++];
//    const QString &workingDir = vegStatsTask.GetFilePath("");
//    const QStringList &spectralIndicatorExtractionArgs = {
//            "-s", QString::number(jobCtx.event.siteId),
//            "-i", tileResultFileInfo.resultFile,
//            "-p", prdInfo.parentProductInfo.name,
//            "-w", workingDir
//    };

//    steps.append(CreateTaskStep(vegStatsTask, "NdviVegetationStats", spectralIndicatorExtractionArgs));

//    return curTaskIdx;
//}

int LaiRetrievalHandlerL3BIndividual::GetStepsForAnglesCreation(QList<TaskToSubmit> &allTasksList, int curTaskIdx,
                            ResultFileInfo &tileResultFileInfo, NewStepList &steps, QStringList &cleanupTemporaryFilesList) {
    TaskToSubmit &createAnglesTask = allTasksList[curTaskIdx++];
    TaskToSubmit &gdalTranslateNoDataTask = allTasksList[curTaskIdx++];
    TaskToSubmit &anglesCreateVrtTask = allTasksList[curTaskIdx++];
    TaskToSubmit &anglesResampleTask = allTasksList[curTaskIdx++];

    const auto & anglesSmallResFileName = createAnglesTask.GetFilePath("angles_small_res.tif");
    const auto & anglesSmallResNoDataFileName = gdalTranslateNoDataTask.GetFilePath("angles_small_res_no_data.tif");
    const auto & anglesVrtFileName = anglesCreateVrtTask.GetFilePath("angles.vrt");
    tileResultFileInfo.anglesFile = anglesResampleTask.GetFilePath("angles_resampled.tif");

    const QStringList &createAnglesArgs = GetCreateAnglesArgs(tileResultFileInfo.productMetadataFile, anglesSmallResFileName);
    const QStringList &gdalSetAnglesNoDataArgs = GetGdalTranslateAnglesNoDataArgs(anglesSmallResFileName, anglesSmallResNoDataFileName);
    const QStringList &gdalBuildAnglesVrtArgs = GetGdalBuildAnglesVrtArgs(anglesSmallResNoDataFileName, anglesVrtFileName);
    const QStringList &gdalResampleAnglesArgs = GetGdalTranslateResampleAnglesArgs(anglesVrtFileName, tileResultFileInfo.anglesFile);

    steps.append(CreateTaskStep(createAnglesTask, "CreateAnglesRaster", createAnglesArgs));
    steps.append(CreateTaskStep(gdalTranslateNoDataTask, "gdal_translate", gdalSetAnglesNoDataArgs));
    steps.append(CreateTaskStep(anglesCreateVrtTask, "gdalbuildvrt", gdalBuildAnglesVrtArgs));
    steps.append(CreateTaskStep(anglesResampleTask, "gdal_translate", gdalResampleAnglesArgs));
    cleanupTemporaryFilesList.append(anglesSmallResFileName);
    cleanupTemporaryFilesList.append(anglesSmallResNoDataFileName);
    cleanupTemporaryFilesList.append(anglesVrtFileName);
    cleanupTemporaryFilesList.append(tileResultFileInfo.anglesFile);

    return curTaskIdx;
}

int LaiRetrievalHandlerL3BIndividual::GetStepsForMonoDateBI(const L3BJobContext &jobCtx, QList<TaskToSubmit> &allTasksList,
                           int curTaskIdx, const QString &indexName, ResultFileInfo &tileResultFileInfo, NewStepList &steps,
                           QStringList &cleanupTemporaryFilesList) {
    const QString &indexNameCaps = indexName.toUpper();
    TaskToSubmit &biProcessorTask = allTasksList[curTaskIdx++];
    TaskToSubmit &biDomainFlagsTask = allTasksList[curTaskIdx++];
    TaskToSubmit &quantifyBIImageTask = allTasksList[curTaskIdx++];
    const auto & BIFileName = biProcessorTask.GetFilePath(indexNameCaps + "_mono_date_img.tif");
    const auto & quantifiedBIFileName = quantifyBIImageTask.GetFilePath(indexNameCaps + "_mono_date_img_16.tif");
    const QStringList &BIProcessorArgs = GetLaiProcessorArgs(tileResultFileInfo.productMetadataFile, tileResultFileInfo.anglesFile,
                                                                    jobCtx.resolutionStr, jobCtx.laiCfgFile,
                                                                    BIFileName, indexName);
    steps.append(CreateTaskStep(biProcessorTask, "BVLaiNewProcessor" + indexNameCaps, BIProcessorArgs));

    const auto & domainFlagsFileName = biDomainFlagsTask.GetFilePath(indexNameCaps + "_out_domain_flags.tif");
    const auto & correctedBIFileName = biDomainFlagsTask.GetFilePath(indexNameCaps + "_corrected_mono_date.tif");
    const QStringList &outDomainFlagsArgs = GetGenerateOutputDomainFlagsArgs(tileResultFileInfo.productMetadataFile, BIFileName,
                                                                jobCtx.laiCfgFile, indexName,
                                                                tileResultFileInfo.inPrdExtMsk,
                                                                domainFlagsFileName,  correctedBIFileName,
                                                                jobCtx.resolutionStr);
    steps.append(CreateTaskStep(biDomainFlagsTask, "Generate" + indexNameCaps + "InDomainQualityFlags", outDomainFlagsArgs));

    const QStringList &quantifyFcoverImageArgs = GetQuantifyImageArgs(correctedBIFileName, quantifiedBIFileName);
    steps.append(CreateTaskStep(quantifyBIImageTask, "Quantify"+indexNameCaps + "Image", quantifyFcoverImageArgs));
    // save the file to be sent to product formatter
    tileResultFileInfo.biDomainFlagsFile = domainFlagsFileName;
    tileResultFileInfo.resultFile = quantifiedBIFileName;

    cleanupTemporaryFilesList.append(BIFileName);
    cleanupTemporaryFilesList.append(domainFlagsFileName);
    cleanupTemporaryFilesList.append(correctedBIFileName);
    cleanupTemporaryFilesList.append(quantifiedBIFileName);

    return curTaskIdx;
}

int LaiRetrievalHandlerL3BIndividual::GetStepsForInDomainFlags(const L3BJobContext &jobCtx, QList<TaskToSubmit> &allTasksList, int curTaskIdx,
                            ResultFileInfo &tileResultFileInfo, NewStepList &steps, QStringList &) {
    TaskToSubmit &inputDomainTask = allTasksList[curTaskIdx++];
    tileResultFileInfo.inDomainFlagsFile = inputDomainTask.GetFilePath("Input_domain_flags.tif");
    const QStringList &inDomainFlagsArgs = GetGenerateInputDomainFlagsArgs(tileResultFileInfo.productMetadataFile,
                                                                jobCtx.laiCfgFile, tileResultFileInfo.inDomainFlagsFile,
                                                                jobCtx.resolutionStr);
    steps.append(CreateTaskStep(inputDomainTask, "GenerateInDomainQualityFlags", inDomainFlagsArgs));

    return curTaskIdx;
}


void LaiRetrievalHandlerL3BIndividual::WriteExecutionInfosFile(const QString &executionInfosPath,
                                               const ResultFileInfo &resultFiles) {
    std::ofstream executionInfosFile;
    try
    {
        executionInfosFile.open(executionInfosPath.toStdString().c_str(), std::ofstream::out);
        executionInfosFile << "<?xml version=\"1.0\" ?>" << std::endl;
        executionInfosFile << "<metadata>" << std::endl;
        executionInfosFile << "  <General>" << std::endl;
        executionInfosFile << "  </General>" << std::endl;

        executionInfosFile << "  <XML_files>" << std::endl;
        executionInfosFile << "    <XML_" << std::to_string(0) << ">" << resultFiles.productMetadataFile.toStdString()
                           << "</XML_" << std::to_string(0) << ">" << std::endl;
        executionInfosFile << "  </XML_files>" << std::endl;
        executionInfosFile << "</metadata>" << std::endl;
        executionInfosFile.close();
    } catch(...)  {}
}

void LaiRetrievalHandlerL3BIndividual::WriteInputPrdIdFile(const QString &outFilePath,
                                               const ProductInfo &prdInfo) {
    std::ofstream outFile;
    try
    {
        outFile.open(outFilePath.toStdString().c_str(), std::ofstream::out);
        outFile << prdInfo.parentProductInfo.productId << std::endl;
        outFile.close();
    } catch(...) {}
}

void LaiRetrievalHandlerL3BIndividual::HandleProduct(const L3BJobContext &jobCtx, const IndicatorDescription &indexDescr,
                                            const ProductInfo &prdInfo, QList<TaskToSubmit> &allTasksList) {
    int tasksStartIdx = allTasksList.size();
    // create the tasks
    CreateTasksForNewProduct(jobCtx, indexDescr, allTasksList);

    QList<std::reference_wrapper<TaskToSubmit>> allTasksListRef;
    for(int i = tasksStartIdx; i < allTasksList.size(); i++) {
        const TaskToSubmit &task = allTasksList.at(i);
        allTasksListRef.append((TaskToSubmit&)task);
    }
    // submit all tasks
    SubmitTasks(*jobCtx.pCtx, jobCtx.event.jobId, allTasksListRef);

    NewStepList steps;

    steps += GetStepsForNewProduct(jobCtx, prdInfo, indexDescr, allTasksList, tasksStartIdx);
    jobCtx.pCtx->SubmitSteps(steps);
}

void LaiRetrievalHandlerL3BIndividual::SubmitEndOfLaiTask(EventProcessingContext &ctx,
                                                const JobSubmittedEvent &event,
                                                const QList<TaskToSubmit> &allTasksList) {
    // add the end of lai job that will perform the cleanup
    QList<std::reference_wrapper<const TaskToSubmit>> endOfJobParents;
    for(const TaskToSubmit &task: allTasksList) {
        if(task.moduleName == "product-formatter" ||
                task.moduleName == "files-remover") {
            endOfJobParents.append(task);
        }
    }
    // we add a task in order to wait for all product formatter to finish.
    // This will allow us to mark the job as finished and to remove the job folder
    TaskToSubmit endOfJobDummyTask{"end-of-job", {}};
    endOfJobDummyTask.parentTasks.append(endOfJobParents);
    SubmitTasks(ctx, event.jobId, {endOfJobDummyTask});
    ctx.SubmitSteps({CreateTaskStep(endOfJobDummyTask, "EndOfJob", QStringList())});
}

void LaiRetrievalHandlerL3BIndividual::HandleJobSubmittedImpl(EventProcessingContext &ctx,
                                             const JobSubmittedEvent &evt)
{
    L3BJobContext jobCtx(this, &ctx, evt);

    if (jobCtx.indicesToCompute.size() == 0) {
        ctx.MarkJobFailed(evt.jobId);
        throw std::runtime_error(
            QStringLiteral("ERROR: No vegetation or spectral index was configured to be generated")
                    .toStdString());
    }

    //container for all task
    QList<TaskToSubmit> allTasksList;

    for (const IndicatorDescription indexDescr: jobCtx.indicesToCompute) {

        // Moved this from the GetProcessingDefinitionImpl function as it might be time consuming and scheduler will
        // throw exception if timeout exceeded

        ProductList prdsToProcess;
        int ret = UpdateJobSubmittedParamsFromSchedReq(jobCtx, indexDescr, prdsToProcess);
        // no products available from the scheduling ... mark also the job as failed
        if (ret == 0) {
            ctx.MarkJobFailed(evt.jobId);
            throw std::runtime_error(
                        QStringLiteral("L3B Scheduled job with id %1 for site %2 marked as done as no products are available for now to process").
                                             arg(evt.jobId).arg(evt.siteId).toStdString());
        } else if (ret == -1) {
            // custom job
            auto parameters = QJsonDocument::fromJson(evt.parametersJson.toUtf8()).object();
            const QStringList &prdNames = GetInputProductNames(parameters);
            prdsToProcess = ctx.GetProducts(evt.siteId, prdNames);
        }
        // extract the full paths to avoid extracting product info one by one
        std::unordered_map<QString, Product> mapInfoPrds;
        std::for_each(prdsToProcess.begin(), prdsToProcess.end(), [&mapInfoPrds](const Product &prd) {
            mapInfoPrds[prd.fullPath] = prd;
        });

        // create and submit the tasks for the received products
        const QList<ProductDetails> &productDetails = ProcessorHandlerHelper::GetProductDetails(prdsToProcess, ctx);
        if(productDetails.size() == 0) {
            ctx.MarkJobFailed(evt.jobId);
            throw std::runtime_error(
                QStringLiteral("No products provided at input or no products available in the specified interval").
                        toStdString());
        }
        const QSet<QString> &tilesFilter = GetTilesFilter(jobCtx);
        // create structures providing the models for each tile
        for(const ProductDetails &prdDetails: productDetails) {
            if (FilterTile(tilesFilter, prdDetails)) {
                std::unique_ptr<ProductHelper> helper = ProductHelperFactory::GetProductHelper(prdDetails);
                const QStringList &metaFiles = helper->GetProductMetadataFiles();
                if (metaFiles.size() == 0) {
                    continue;
                }
                ProductInfo prdInfo;
                prdInfo.productMetadataFile = metaFiles[0];
                prdInfo.parentProductInfo = prdDetails.GetProduct();
                const QStringList &extMasks = helper->GetProductMasks();
                if (extMasks.size() > 0 ) {
                    prdInfo.prdExternalMskFile = extMasks[0];
                }
                const QStringList &tiles = prdDetails.GetProduct().tiles;
                if (tiles.size() == 0) {
                    Logger::error(QStringLiteral("InitTileResultFiles: the product %1 does not have any associated tiles!")
                                  .arg(metaFiles[0]));
                    continue;
                }
                prdInfo.tileId = tiles.at(0);
                HandleProduct(jobCtx, indexDescr, prdInfo, allTasksList);
            }
        }
    }
    // we add a task in order to wait for all product formatter to finish.
    // This will allow us to mark the job as finished and to remove the job folder
    SubmitEndOfLaiTask(ctx, evt, allTasksList);
}

void LaiRetrievalHandlerL3BIndividual::HandleTaskFinishedImpl(EventProcessingContext &ctx,
                                             const TaskFinishedEvent &event)
{
    if (event.module == "end-of-job") {
        ctx.MarkJobFinished(event.jobId);
        // Now remove the job folder containing temporary files
        RemoveJobFolder(ctx, event.jobId, processorDescr.shortName);
    }
    if ((event.module == "product-formatter")) {
        const QString &prodName = GetOutputProductName(ctx, event);
        const QString &productFolder = GetOutputProductPath(ctx, event);
        const IndicatorDescription &indDescr = GetTaskSavedIndicator(ctx, event);
        GenericHighLevelProductHelper prdHelper(productFolder);
        if(prodName != "" && prdHelper.HasValidStructure()) {
            const QString &quicklook = GetProductFormatterQuicklook(ctx, event);
            const QString &footPrint = GetProductFormatterFootprint(ctx, event);
            const QStringList &prodTiles = prdHelper.GetTileIdsFromProduct();
            // get the satellite id for the product
            const QMap<Satellite, TileList> &siteTiles = GetSiteTiles(ctx, event.siteId);
            Satellite satId = Satellite::Invalid;
            for(const auto &tileId : prodTiles) {
                // we assume that all the tiles from the product are from the same satellite
                // in this case, we get only once the satellite Id for all tiles
                if(satId == Satellite::Invalid) {
                    satId = ProcessorHandlerHelper::GetSatIdForTile(siteTiles, tileId);
                    // ignore tiles for which the satellite id cannot be determined
                    if(satId != Satellite::Invalid) {
                        break;
                    }
                }
            }

            // Insert the product into the database
            const ProductIdsList &prdIds = GetOutputProductParentProductIds(ctx, event);
            int ret = ctx.InsertProduct({ indDescr.prdType, event.processorId, static_cast<int>(satId), event.siteId, event.jobId,
                                productFolder, prdHelper.GetAcqDate(), prodName,
                                quicklook, footPrint, std::experimental::nullopt, prodTiles, prdIds });
            Logger::debug(QStringLiteral("InsertProduct for %1 returned %2").arg(prodName).arg(ret));

            // Cleanup the currently processing products for the current job
            Logger::info(QStringLiteral("Cleaning up the file containing currently processing products for output product %1 and folder %2 and site id %3 and job id %4").
                         arg(prodName).arg(productFolder).arg(event.siteId).arg(event.jobId));
            const QString &curProcPrdsFilePath = GetSiteCurrentProcessingPrdsFile(ctx, event.jobId, event.siteId, indDescr.name);
            QStringList prdStrIds;
            for(int id: prdIds) { prdStrIds.append(QString::number(id)); }
            ProcessorHandlerHelper::CleanupCurrentProductIdsForJob(curProcPrdsFilePath, event.jobId, prdStrIds);

        } else {
            Logger::error(QStringLiteral("Cannot insert into database the product with name %1 and folder %2").arg(prodName).arg(productFolder));
            // We might have several L3B products, we should not mark it at failed here as
            // this will stop also all other L3B processings that might be successful
            //ctx.MarkJobFailed(event.jobId);
        }
    }
}

QStringList LaiRetrievalHandlerL3BIndividual::GetCreateAnglesArgs(const QString &inputProduct, const QString &anglesFile) {
    return { "CreateAnglesRaster",
           "-xml", inputProduct,
           "-out", anglesFile
    };
}

QStringList LaiRetrievalHandlerL3BIndividual::GetGdalTranslateAnglesNoDataArgs(const QString &anglesFile,
                                                                        const QString &resultAnglesFile) {
    return {
            "-of", "GTiff", "-a_nodata", "-10000",
            anglesFile,
            resultAnglesFile
    };
}

QStringList LaiRetrievalHandlerL3BIndividual::GetGdalBuildAnglesVrtArgs(const QString &anglesFile,
                                                                 const QString &resultVrtFile) {
    return {
             "-tr", "10", "10", "-r", "bilinear", "-srcnodata", "-10000", "-vrtnodata", "-10000",
            resultVrtFile,
            anglesFile
    };
}

QStringList LaiRetrievalHandlerL3BIndividual::GetGdalTranslateResampleAnglesArgs(const QString &vrtFile,
                                                                        const QString &resultResampledAnglesFile) {
    return {
            vrtFile,
            resultResampledAnglesFile
    };
}

QStringList LaiRetrievalHandlerL3BIndividual::GetSpectralIndicatorsExtractionArgs(const QString &inputProduct, const QString &indicator,
                                                                           const QString &msksFlagsFile, const QString &indicatorFile) {
    return { "Sen4XRadiometricIndices",
           "-xml", inputProduct,
           "-msks", msksFlagsFile,
           "-list", L3BJobContext::indicatorsDescriptions[indicator].category + ":" +
                L3BJobContext::indicatorsDescriptions[indicator].paramName,
           "-out", indicatorFile
    };
}

QStringList LaiRetrievalHandlerL3BIndividual::GetLaiProcessorArgs(const QString &xmlFile, const QString &anglesFileName,
                                                           const QString &resolution, const QString &laiBandsCfg,
                                                           const QString &monoDateLaiFileName, const QString &indexName) {
    QString outParamName = QString("-out") + indexName;
    return { "BVLaiNewProcessor",
        "-xml", xmlFile,
        "-angles", anglesFileName,
        outParamName, monoDateLaiFileName,
        "-outres", resolution,
        "-laicfgs", laiBandsCfg
    };
}

QStringList LaiRetrievalHandlerL3BIndividual::GetGenerateInputDomainFlagsArgs(const QString &xmlFile,  const QString &laiBandsCfg,
                                                            const QString &outFlagsFileName, const QString &outRes) {
    return { "GenerateDomainQualityFlags",
        "-xml", xmlFile,
        "-laicfgs", laiBandsCfg,
        "-outf", outFlagsFileName,
        "-outres", outRes
    };
}

QStringList LaiRetrievalHandlerL3BIndividual::GetGenerateOutputDomainFlagsArgs(const QString &xmlFile, const QString &laiRasterFile,
                                                            const QString &laiBandsCfg, const QString &indexName,
                                                            const QString &extMsk, const QString &outFlagsFileName,
                                                            const QString &outCorrectedLaiFile, const QString &outRes)  {
    QStringList args = { "GenerateDomainQualityFlags",
        "-xml", xmlFile,
        "-in", laiRasterFile,
        "-laicfgs", laiBandsCfg,
        "-indextype", indexName,
        "-outf", outFlagsFileName,
        "-out", outCorrectedLaiFile,
        "-outres", outRes,
    };
    if(extMsk.size() > 0) {
        args += "-extmsk";
        args += extMsk;
    }
    return args;
}

QStringList LaiRetrievalHandlerL3BIndividual::GetQuantifyImageArgs(const QString &inFileName, const QString &outFileName)  {
    return { "QuantifyImage",
        "-in", inFileName,
        "-out", outFileName
    };
}

QStringList LaiRetrievalHandlerL3BIndividual::GetMonoDateMskFlagsArgs(const QString &inputProduct,
                                                               const QString &extMsk,
                                                               const QString &monoDateMskFlgsFileName,
                                                               const QString &monoDateMskFlgsResFileName,
                                                               const QString &resStr) {
    QStringList args = { "GenerateLaiMonoDateMaskFlags",
      "-inxml", inputProduct,
      "-out", monoDateMskFlgsFileName,
      "-outres", resStr,
      "-outresampled", monoDateMskFlgsResFileName
    };
    if(extMsk.size() > 0) {
        args += "-extmsk";
        args += extMsk;
    }
    return args;
}

QStringList LaiRetrievalHandlerL3BIndividual::GetProductFormatterArgs(TaskToSubmit &productFormatterTask, const L3BJobContext &jobCtx,
                                                                      const ProductInfo &prdInfo, const IndicatorDescription &indexDescr,
                                                                      const ResultFileInfo &resultFilesInfo) {

    //const auto &targetFolder = productFormatterTask.GetFilePath("");
    const auto &executionInfosPath = productFormatterTask.GetFilePath("executionInfos.xml");
    const auto &inputPrdsIdsInfosPath = productFormatterTask.GetFilePath(PRODUCT_FORMATTER_IN_PRD_IDS_FILE);

    WriteExecutionInfosFile(executionInfosPath, resultFilesInfo);
    WriteInputPrdIdFile(inputPrdsIdsInfosPath, prdInfo);
    SaveTaskIndicator(productFormatterTask, indexDescr.name);

    QStringList additionalArgs = {"-il"};
    additionalArgs.append(resultFilesInfo.productMetadataFile);

    if(jobCtx.lutFile.size() > 0) {
        additionalArgs += "-lut";
        additionalArgs += jobCtx.lutFile;
    }

    additionalArgs += "-processor.vegetation.laistatusflgs";
    additionalArgs += GetProductFormatterTile(resultFilesInfo.tileId);
    additionalArgs += resultFilesInfo.statusFlagsFileResampled;

    additionalArgs += "-prdnamesuffix";
    additionalArgs += ("T" + resultFilesInfo.tileId);

    if (jobCtx.bGenInDomainFlags) {
        additionalArgs += "-processor.vegetation.indomainflgs";
        additionalArgs += GetProductFormatterTile(resultFilesInfo.tileId);
        additionalArgs += resultFilesInfo.inDomainFlagsFile;
    }

    if (indexDescr.isBI) {
        additionalArgs += "-processor.vegetation." + indexDescr.name + "monodate";
        additionalArgs += GetProductFormatterTile(resultFilesInfo.tileId);
        additionalArgs += resultFilesInfo.resultFile;
        additionalArgs += "-processor.vegetation." + indexDescr.name + "domainflgs";
        additionalArgs += GetProductFormatterTile(resultFilesInfo.tileId);
        additionalArgs += resultFilesInfo.biDomainFlagsFile;
    } else {
        additionalArgs += "-processor.vegetation." + indexDescr.name;
        additionalArgs += GetProductFormatterTile(resultFilesInfo.tileId);
        additionalArgs += resultFilesInfo.resultFile;
    }
    if (IsCloudOptimizedGeotiff(jobCtx.configParameters)) {
        additionalArgs += "-cog";
        additionalArgs += "1";
    }

    if (!jobCtx.bGenMosaic) {
        additionalArgs += "-aggregatetiles";
        additionalArgs += "0";
    }



    return GetDefaultProductFormatterArgs(*jobCtx.pCtx, productFormatterTask, jobCtx.event.jobId, jobCtx.event.siteId, "L3B" + indexDescr.name.toUpper(), "",
                                         "vegetation", additionalArgs, false, executionInfosPath, true, indexDescr.name);
}

QStringList LaiRetrievalHandlerL3BIndividual::GetCompositeDuplicateDatesArgs(const QString &outCompositeFile) {
    return {"-i", outCompositeFile};
}

const QString& LaiRetrievalHandlerL3BIndividual::GetDefaultCfgVal(std::map<QString, QString> &configParameters, const QString &key, const QString &defVal) {
    auto search = configParameters.find(key);
    if(search != configParameters.end()) {
        return search->second;
    }
    return defVal;
}

QSet<QString> LaiRetrievalHandlerL3BIndividual::GetTilesFilter(const L3BJobContext &jobCtx)
{
    QString strTilesFilter;
    if(jobCtx.parameters.contains("tiles_filter")) {
        const auto &value = jobCtx.parameters["tiles_filter"];
        if(value.isString()) {
            strTilesFilter = value.toString();
        }
    }
    if (strTilesFilter.isEmpty()) {
        auto it = jobCtx.configParameters.find("processor.l3b.lai.tiles_filter");
        if (it != jobCtx.configParameters.end()) {
            strTilesFilter = it->second;
        }
    }
    QSet<QString> retSet;
    // accept any of these separators
    const QStringList &tilesList = strTilesFilter.split(',');
    for (const QString &strTile: tilesList) {
        const QString &strTrimmedTile = strTile.trimmed();
        if(!strTrimmedTile.isEmpty()) {
            retSet.insert(strTrimmedTile);
        }
    }

    return retSet;
}

bool LaiRetrievalHandlerL3BIndividual::FilterTile(const QSet<QString> &tilesSet, const ProductDetails &prdDetails)
{
    const QStringList &tileIds = prdDetails.GetProduct().tiles;
    if (tileIds.size() == 0) {
        Logger::error(QStringLiteral("FilterTile: product %1 does not have any associated tiles!")
                      .arg(prdDetails.GetProduct().fullPath));
        return false;
    }
    return (tilesSet.empty() || tilesSet.contains(tileIds.at(0)));
}

void LaiRetrievalHandlerL3BIndividual::InitTileResultFiles(const ProductInfo &tileInfo, ResultFileInfo &tileResultFileInfo) {
    tileResultFileInfo.productMetadataFile = tileInfo.productMetadataFile;
    tileResultFileInfo.inPrdExtMsk = tileInfo.prdExternalMskFile;
    tileResultFileInfo.tileId = tileInfo.tileId;
}

ProcessorJobDefinitionParams LaiRetrievalHandlerL3BIndividual::GetProcessingDefinitionImpl(SchedulingContext &ctx, int siteId, int scheduledDate,
                                                          const ConfigurationParameterValueMap &requestOverrideCfgValues)
{
    ProcessorJobDefinitionParams params;

    QDateTime seasonStartDate;
    QDateTime seasonEndDate;
    // extract the scheduled date
    QDateTime qScheduledDate = QDateTime::fromTime_t(scheduledDate);
    bool success = GetSeasonStartEndDates(ctx, siteId, seasonStartDate, seasonEndDate, qScheduledDate, requestOverrideCfgValues);
    // if cannot get the season dates
    if(!success) {
        success = GetBestSeasonToMatchDate(ctx, siteId, seasonStartDate, seasonEndDate, qScheduledDate, requestOverrideCfgValues);
        if(!success) {
            Logger::debug(QStringLiteral("Scheduler L3B: Error getting season start dates for site %1 for scheduled date %2!")
                          .arg(siteId)
                          .arg(qScheduledDate.toString()));
            return params;
        }
    }
    if(!seasonStartDate.isValid()) {
        Logger::error(QStringLiteral("Scheduler L3B: Season start date for site ID %1 is invalid in the database!")
                      .arg(siteId));
        return params;
    }

    ConfigurationParameterValueMap mapCfg = ctx.GetConfigurationParameters(QString(L3B_CFG_PREFIX), siteId, requestOverrideCfgValues);

    // we might have an offset in days from starting the downloading products to start the L3B scheduling
    int startSeasonOffset = mapCfg[QString(L3B_CFG_PREFIX) + "start_season_offset"].value.toInt();
    if (startSeasonOffset == 0) {
        startSeasonOffset = 14;
    }
    QDateTime currentDate = QDateTime::currentDateTime();
    // if the current date or greater than the scheduled date, start the schedule regardless of the ancestor products processing status (NRT)
    if (currentDate.date() <= qScheduledDate.date()) {
        Logger::debug(QStringLiteral("Scheduler L3B: The current date %1 is equals or greater than the scheduled date %2 for site %3 (NRT). "
                                     "The completness of processing for ancestor products will not be cheked and the job will be schedules anyway")
                      .arg(siteId)
                      .arg(qScheduledDate.toString())
                      .arg(currentDate.toString()));
    } else {
        QDateTime minScheduleDate = seasonStartDate.addDays(startSeasonOffset);
        // if scheduled date is less than the minimum scheduling date, return invalid to pass to the next date
        if (qScheduledDate >= minScheduleDate) {
            // check if the ancestor products were created
            if (!CheckAllAncestorProductCreation(ctx, siteId, ProductType::L3BProductTypeId, seasonStartDate, qScheduledDate) ||
                 (qScheduledDate > seasonEndDate.addDays(1))) {
                // do not trigger anymore the schedule.
                params.schedulingFlags = SchedulingFlags::SCH_FLG_RETRY_LATER;
                Logger::error(QStringLiteral("L3B Scheduled job execution at date %1 for site %2 will be retried later: Not all input products were "
                                             "yet produced")
                              .arg(qScheduledDate.toString())
                               .arg(siteId));
            }
        } else {
            // if in the first 2 weeks of the season, and no products yet, do noop
            params.schedulingFlags = SchedulingFlags::SCH_FLG_NOOP_AND_SCHEDULE_NEXT;
            Logger::error(QStringLiteral("L3B Scheduled job execution at date %1 for site %2 is within the first %3 days of the season. Noop and schedule next ...")
                          .arg(qScheduledDate.toString())
                          .arg(siteId)
                          .arg(startSeasonOffset));
        }
    }
    params.jsonParameters = "{ \"scheduled_job\": \"1\"";
    params.jsonParameters.append(", \"start_date\": \"" + seasonStartDate.toString("yyyyMMdd") + "\", " +
                                 "\"end_date\": \"" + qScheduledDate.toString("yyyyMMdd") + "\", " +
                                 "\"season_start_date\": \"" + seasonStartDate.toString("yyyyMMdd") + "\", " +
                                 "\"season_end_date\": \"" + seasonEndDate.toString("yyyyMMdd") + "\"}");
    params.isValid = true;

    return params;
}

int LaiRetrievalHandlerL3BIndividual::UpdateJobSubmittedParamsFromSchedReq(const L3BJobContext &jobCtx, const IndicatorDescription &indexDescr, ProductList &prdsToProcess) {
    int jobVal;
    QString strStartDate, strEndDate;
    if(ProcessorHandlerHelper::GetParameterValueAsInt(jobCtx.parameters, "scheduled_job", jobVal) && (jobVal == 1) &&
            ProcessorHandlerHelper::GetParameterValueAsString(jobCtx.parameters, "start_date", strStartDate) &&
            ProcessorHandlerHelper::GetParameterValueAsString(jobCtx.parameters, "end_date", strEndDate) &&
            jobCtx.parameters.contains("input_products")) {
        if (!jobCtx.parameters.contains("input_products") || jobCtx.parameters["input_products"].toArray().size() == 0) {
            auto startDate = ProcessorHandlerHelper::GetLocalDateTime(strStartDate);
            auto endDate = ProcessorHandlerHelper::GetLocalDateTime(strEndDate);

            QString strSeasonStartDate, strSeasonEndDate;
            QDateTime seasonStartDate, seasonEndDate;
            if (ProcessorHandlerHelper::GetParameterValueAsString(jobCtx.parameters, "season_start_date", strSeasonStartDate) &&
                    ProcessorHandlerHelper::GetParameterValueAsString(jobCtx.parameters, "season_end_date", strSeasonEndDate)) {
                seasonStartDate = ProcessorHandlerHelper::GetLocalDateTime(strSeasonStartDate);
                seasonEndDate = ProcessorHandlerHelper::GetLocalDateTime(strSeasonEndDate);
                // we consider only products in the current season
                if(startDate < seasonStartDate.addDays(-1)) {
                    startDate = seasonStartDate.addDays(-1);
                }
                if (endDate > seasonEndDate.addDays(1)) {
                    endDate = seasonEndDate.addDays(1);
                }
            }
            Logger::info(QStringLiteral("L3B Scheduled job received for siteId = %1, startDate=%2, endDate=%3").
                         arg(jobCtx.event.siteId).arg(startDate.toString("yyyyMMddTHHmmss")).arg(endDate.toString("yyyyMMddTHHmmss")));
            prdsToProcess  = GetL2AProductsNotProcessedProductProvenance(jobCtx, indexDescr, startDate, endDate);
            return prdsToProcess.size();
        }
    }
    return -1;
}

// TODO: This function should be updated to use the ProcessorHandlerHelper::EnsureMonoDateProductUniqueProc function
ProductList LaiRetrievalHandlerL3BIndividual::GetL2AProductsNotProcessedProductProvenance(const L3BJobContext &jobCtx,
                                                                  const IndicatorDescription &indexDescr, const QDateTime &startDate, const QDateTime &endDate) {

    ProductType l2ProdType = ProductType::L2AProductTypeId;
    if(IsL2AValidityMaskEnabled(*jobCtx.pCtx, jobCtx.parameters, jobCtx.event.siteId)) {
        l2ProdType = ProductType::MaskedL2AProductTypeId;
    }

    // Get the list of L2A products already processed products as L3B
    const ProductList &existingPrds = jobCtx.pCtx->GetParentProductsInProvenance(jobCtx.event.siteId,
                                                {l2ProdType}, indexDescr.prdType, startDate, endDate);
    // Get the list of L2A products NOT processed products as L3B
    const ProductList &missingPrds = jobCtx.pCtx->GetParentProductsNotInProvenance(jobCtx.event.siteId,
                                            {l2ProdType}, indexDescr.prdType, startDate, endDate);

    std::unordered_map<int, int> mapPresence;
    std::for_each(existingPrds.begin(), existingPrds.end(), [&mapPresence](const Product &prd) {
        mapPresence[prd.productId] = 1;
    });

    ProductList newL2APrdsToProcess;

    Logger::info(QStringLiteral("Found a number of %1 L2A products not processed in L3B %2").arg(missingPrds.size()).arg(indexDescr.name));
    if (missingPrds.size() == 0) {
        return newL2APrdsToProcess;
    }
    for (const Product &prd: missingPrds) {
        Logger::info(QStringLiteral("  ==> Missing L2A from L3B %1: %2").arg(indexDescr.name).arg(prd.fullPath));
    }

    // Get the active jobs of this site
    const JobIdsList &activeJobIds = jobCtx.pCtx->GetActiveJobIds(this->processorDescr.processorId, jobCtx.event.siteId);

    // Get the file containing the product ids currently processing by all jobs of this site
    const QString &filePath = GetSiteCurrentProcessingPrdsFile(*jobCtx.pCtx, jobCtx.event.jobId, jobCtx.event.siteId, indexDescr.name);
    QDir().mkpath(QFileInfo(filePath).absolutePath());
    QFile file( filePath );
    // First read all the entries in the file to see what are the products that are currently processing
    QMap<int, int> curProcPrds;
    if (file.open(QIODevice::ReadOnly)) {
        QTextStream in(&file);
        while (!in.atEnd()) {
            const QString &line = in.readLine();
            const QStringList &pieces = line.split(';');
            if (pieces.size() == 2) {
                int prdId = pieces[0].toInt();
                int jobId = pieces[1].toInt();
                // add only product ids that were not yet processed or that are currently processing in some active jobs
                if (prdId != 0) {
                    // maybe the product was already created meanwhile by a custom job, in this case we should remove it
                    if (mapPresence.find(prdId) != mapPresence.end()) {
                        continue;
                    }
                    // if the job processing the product is still active, keep the product
                    if (activeJobIds.contains(jobId)) {
                        curProcPrds[prdId] = jobId;
                    }
                }
            }
        }
        file.close();
    }
    // add the products that will be processed next
    for (int i = 0; i<missingPrds.size(); i++) {
        if (curProcPrds.find(missingPrds[i].productId) == curProcPrds.end()) {
            curProcPrds[missingPrds[i].productId] = jobCtx.event.jobId;
            newL2APrdsToProcess.append(missingPrds[i]);
        }
        // else, if the product was already in this list, then it means it was already scheduled for processing
        // by another schedule operation
    }

    if ( file.open(QIODevice::ReadWrite | QFile::Truncate) )
    {
        QTextStream stream( &file );
        for(auto prdInfo : curProcPrds.keys()) {
            stream << prdInfo << ";" << curProcPrds.value(prdInfo) << '\n';
        }
    }

    Logger::info(QStringLiteral("A number of %1 L2A products needs to be processed in L3B %2 after checking already launched products").
                 arg(newL2APrdsToProcess.size()).arg(indexDescr.name));
    return newL2APrdsToProcess;
}

QString LaiRetrievalHandlerL3BIndividual::GetSiteCurrentProcessingPrdsFile(EventProcessingContext &ctx, int jobId, int siteId, const QString &indexName) {
    const QString &filename = QString(CURRENT_PROC_PRDS_FILE_NAME).arg(indexName);
    return QDir::cleanPath(GetFinalProductFolder(ctx, jobId, siteId, indexName) + QDir::separator() + filename);
}

void LaiRetrievalHandlerL3BIndividual::SaveTaskIndicator(TaskToSubmit &task, const QString &indicatorName) {
    const auto &propsFile = task.GetFilePath(INDICATOR_NAME_FILE);
    std::ofstream executionInfosFile;
    try {
        executionInfosFile.open(propsFile.toStdString().c_str(), std::ofstream::out);
        executionInfosFile << indicatorName.toStdString().c_str() << std::endl;
        executionInfosFile.close();
    } catch (...) {
    }
}

LaiRetrievalHandlerL3BIndividual::IndicatorDescription LaiRetrievalHandlerL3BIndividual::GetTaskSavedIndicator(EventProcessingContext &ctx, const TaskFinishedEvent &evt) {
    const QString &prodFolderOutPath = GetTaskOutputPathFromEvt(ctx, evt) + "/" + INDICATOR_NAME_FILE;
    QStringList fileLines = ProcessorHandlerHelper::GetTextFileLines(prodFolderOutPath);
    IndicatorDescription indDescr({"", false, "", "", ProductType::InvalidProductTypeId});
    if(fileLines.size() > 0) {
        const QString &indicatorName = fileLines[0].trimmed();
        indDescr = LaiRetrievalHandlerL3BIndividual::L3BJobContext::indicatorsDescriptions[indicatorName];
    }
    return indDescr;

}
