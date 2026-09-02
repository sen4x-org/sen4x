/*
 * OpticalFeaturesRewrite
 * Rewritten OpticalFeatures application for OTB 9.
 */

#include "otbWrapperApplication.h"
#include "otbWrapperApplicationFactory.h"
#include "otbWrapperInputXML.h"
#include "otbWrapperTypes.h"

#include "../Filters/otbCropTypeFeatureExtractionFilter.h"
#include "../Filters/otbStreamingStatisticsMapFromLabelImageFilter2.h"
#include "../Filters/otbTemporalResamplingFilter.h"

#include "itkCastImageFilter.h"
#include "itkExceptionObject.h"
#include "itkIdentityTransform.h"
#include "itkNearestNeighborInterpolateImageFunction.h"
#include "itkProcessObject.h"
#include "itkTernaryFunctorImageFilter.h"
#include "itkUnaryFunctorImageFilter.h"
#include "itkVectorIndexSelectionCastImageFilter.h"

#include "otbBCOInterpolateImageFunction.h"
#include "otbConcatenateVectorImageFilter.h"
#include "otbFunctorImageFilter.h"
#include "otbGenericRSResampleImageFilter.h"
#include "otbImageFileReader.h"
#include "otbImageList.h"
#include "otbImageListToVectorImageFilter.h"
#include "otbImageToVectorImageCastFilter.h"
#include "otbStreamingResampleImageFilter.h"

#include <algorithm>
#include <cctype>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <map>
#include <memory>
#include <set>
#include <sstream>
#include <string>
#include <time.h>
#include <vector>

namespace
{
namespace fs = std::filesystem;

constexpr double kTargetPixelSizeMeters = 10.0;
constexpr unsigned int kReflectanceBCORadius = 2;
constexpr double kReflectanceBCOAlpha = -0.5;

int getDaysFromEpoch(const std::string &date)
{
    int y = std::stoi(date.substr(0, 4));
    int m = std::stoi(date.substr(4, 2));
    int d = std::stoi(date.substr(6, 2));

    using namespace std::chrono;
    year_month_day ymd{ year{ y }, month{ static_cast<unsigned>(m) },
                        day{ static_cast<unsigned>(d) } };
    if (!ymd.ok()) {
        itkGenericExceptionMacro("Invalid value for a date: " + date);
    }
    return static_cast<int>(sys_days(ymd).time_since_epoch().count());
}

struct SensorPreferences {
    std::string mission;
    int priority;
    int samplingRate;
};

enum class TemporalResamplingMode {
    GapFill,
    Resample,
    GapFillMainMission,
};

struct AddOffsetFunctor {
    float m_Offset;

    AddOffsetFunctor() : m_Offset(0.0f) {}

    bool operator!=(const AddOffsetFunctor &other) const { return m_Offset != other.m_Offset; }

    bool operator==(const AddOffsetFunctor &other) const { return !(*this != other); }

    void SetOffset(float offset) { m_Offset = offset; }

    float operator()(const float &value) const
    {
        const auto applyOffset = [this](const float &pixelValue) { return pixelValue + m_Offset; };
        return applyOffset(value);
    }
};

std::string joinPath(const std::string &left, const std::string &right)
{
    if (left.empty()) {
        return right;
    }
    if (left.back() == '/') {
        return left + right;
    }
    return left + "/" + right;
}

enum class Sentinel2Band { B2, B3, B4, B8, B11, B12, B8A, B5, B6, B7 };

std::string firstEightDigits(const std::string &value);

std::vector<std::string> splitString(const std::string &value, char delimiter)
{
    std::vector<std::string> parts;
    std::stringstream ss(value);
    std::string item;
    while (std::getline(ss, item, delimiter)) {
        parts.push_back(item);
    }
    return parts;
}

typedef otb::Image<uint8_t, 2> UInt8ImageType;
typedef otb::ImageFileReader<UInt8ImageType> UInt8ImageReaderType;
typedef otb::StreamingResampleImageFilter<UInt8ImageType, UInt8ImageType, double>
    UInt8ScalarResampleType;
typedef itk::IdentityTransform<double, 2> IdentityTransformType;

UInt8ImageType::Pointer ResampleMaskToPixelSize(UInt8ImageType *input,
                                                UInt8ScalarResampleType *resampler,
                                                double targetPixelSizeMeters)
{
    input->UpdateOutputInformation();
    auto inSpacing = input->GetSignedSpacing();

    UInt8ImageType::SpacingType outSpacing;
    outSpacing[0] = (inSpacing[0] < 0.0 ? -targetPixelSizeMeters : targetPixelSizeMeters);
    outSpacing[1] = (inSpacing[1] < 0.0 ? -targetPixelSizeMeters : targetPixelSizeMeters);

    itk::FixedArray<double, 2> scale;
    scale[0] = outSpacing[0] / inSpacing[0];
    scale[1] = outSpacing[1] / inSpacing[1];

    auto inOrigin = input->GetOrigin();
    UInt8ImageType::PointType outOrigin;
    outOrigin[0] = inOrigin[0] + 0.5 * inSpacing[0] * (scale[0] - 1.0);
    outOrigin[1] = inOrigin[1] + 0.5 * inSpacing[1] * (scale[1] - 1.0);

    auto inSize = input->GetLargestPossibleRegion().GetSize();
    UInt8ScalarResampleType::SizeType outSize;
    outSize[0] = static_cast<unsigned int>(std::round(inSize[0] / scale[0]));
    outSize[1] = static_cast<unsigned int>(std::round(inSize[1] / scale[1]));

    auto interp = itk::NearestNeighborInterpolateImageFunction<UInt8ImageType, double>::New();
    auto transform = IdentityTransformType::New();
    resampler->SetInput(input);
    resampler->SetInterpolator(interp);
    resampler->SetTransform(transform);
    resampler->SetOutputStartIndex(input->GetLargestPossibleRegion().GetIndex());
    resampler->SetOutputSpacing(outSpacing);
    resampler->SetOutputOrigin(outOrigin);
    resampler->SetOutputSize(outSize);
    resampler->SetEdgePaddingValue(1);

    return resampler->GetOutput();
}

class Sentinel2Product
{
public:
    virtual ~Sentinel2Product() = default;
    virtual std::string GetBandPath(Sentinel2Band band) const = 0;
    virtual std::string GetAcquisitionDateYYYYMMDD() const = 0;
    virtual float GetBandOffset(Sentinel2Band band) const = 0;
    virtual itk::ProcessObject::Pointer
    BuildMask(int targetPixelSizeMeters,
              std::vector<UInt8ImageReaderType::Pointer> &readers,
              std::vector<UInt8ScalarResampleType::Pointer> &resamplers,
              UInt8ImageType::Pointer &outMask) const = 0;
};

class Sen2CorProduct : public Sentinel2Product
{
public:
    Sen2CorProduct(const std::string &mtdPath,
                   const std::string &productRoot,
                   const std::string &granuleName,
                   const std::string &filePrefix,
                   const std::string &acquisitionDateTime,
                   const std::map<int, float> &boaOffsetsByBandId)
        : m_MtdPath(mtdPath),
          m_ProductRoot(productRoot),
          m_GranuleName(granuleName),
          m_AcquisitionDateTime(acquisitionDateTime),
          m_FilePrefix(filePrefix),
          m_BoaOffsetsByBandId(boaOffsetsByBandId)
    {
        fs::path granulePath = fs::path(m_ProductRoot) / "GRANULE" / m_GranuleName;
        fs::path imgDataPath = granulePath / "IMG_DATA";
        m_GranulePath = granulePath.string();
        m_R10mPath = (imgDataPath / "R10m").string();
        m_R20mPath = (imgDataPath / "R20m").string();
    }

    std::string GetBandPath(Sentinel2Band band) const override
    {
        const int res = GetBandNativeResolution(band);
        return BuildBandPath(GetBandToken(band), res);
    }

    std::string GetAcquisitionDateYYYYMMDD() const override
    {
        return firstEightDigits(m_AcquisitionDateTime);
    }

    float GetBandOffset(Sentinel2Band band) const override
    {
        const int bandId = GetBandId(band);
        const auto it = m_BoaOffsetsByBandId.find(bandId);
        if (it == m_BoaOffsetsByBandId.end()) {
            return 0.0f;
        }
        return it->second;
    }

    itk::ProcessObject::Pointer BuildMask(int targetPixelSizeMeters,
                                          std::vector<UInt8ImageReaderType::Pointer> &readers,
                                          std::vector<UInt8ScalarResampleType::Pointer> &resamplers,
                                          UInt8ImageType::Pointer &outMask) const override
    {
        // Sen2Cor SCL is natively provided at 20m in R20m
        const std::string sclPath = BuildSclPath();

        auto sclReader = UInt8ImageReaderType::New();
        sclReader->SetFileName(sclPath);
        auto sclImage = sclReader->GetOutput();
        sclImage->UpdateOutputInformation();
        readers.push_back(sclReader);

        UInt8ImageType::Pointer resampledScl = sclImage;
        if (targetPixelSizeMeters != 20) {
            auto sclPixResampler = UInt8ScalarResampleType::New();
            resampledScl = ResampleMaskToPixelSize(sclImage, sclPixResampler,
                                                   static_cast<double>(targetPixelSizeMeters));
            resampledScl->UpdateOutputInformation();
            resamplers.push_back(sclPixResampler);
        }

        auto filter = otb::NewFunctorFilter([](uint8_t value) -> uint8_t {
            switch (value) {
                case 4: // Vegetation
                case 5: // Not-vegetated
                case 7: // Unclassified
                    return 0;
                default:
                    return 1;
            }
        });
        filter->SetInput(resampledScl);
        outMask = filter->GetOutput();
        return filter.GetPointer();
    }

private:
    int GetBandId(Sentinel2Band band) const
    {
        switch (band) {
            case Sentinel2Band::B2:
                return 1;
            case Sentinel2Band::B3:
                return 2;
            case Sentinel2Band::B4:
                return 3;
            case Sentinel2Band::B8:
                return 7;
            case Sentinel2Band::B11:
                return 11;
            case Sentinel2Band::B12:
                return 12;
            case Sentinel2Band::B8A:
                return 8;
            case Sentinel2Band::B5:
                return 4;
            case Sentinel2Band::B6:
                return 5;
            case Sentinel2Band::B7:
                return 6;
        }
        itkGenericExceptionMacro("Unsupported Sentinel2Band enum value");
    }

    int GetBandNativeResolution(Sentinel2Band band) const
    {
        switch (band) {
            case Sentinel2Band::B11:
            case Sentinel2Band::B12:
            case Sentinel2Band::B8A:
            case Sentinel2Band::B5:
            case Sentinel2Band::B6:
            case Sentinel2Band::B7:
                return 20;
            default:
                return 10;
        }
    }

    std::string GetBandToken(Sentinel2Band band) const
    {
        switch (band) {
            case Sentinel2Band::B2:
                return "B02";
            case Sentinel2Band::B3:
                return "B03";
            case Sentinel2Band::B4:
                return "B04";
            case Sentinel2Band::B8:
                return "B08";
            case Sentinel2Band::B11:
                return "B11";
            case Sentinel2Band::B12:
                return "B12";
            case Sentinel2Band::B8A:
                return "B8A";
            case Sentinel2Band::B5:
                return "B05";
            case Sentinel2Band::B6:
                return "B06";
            case Sentinel2Band::B7:
                return "B07";
        }
        itkGenericExceptionMacro("Unsupported Sentinel2Band enum value");
    }

    std::string BuildBandPath(const std::string &normalizedBand, int res) const
    {
        const std::string dir = (res == 10 ? m_R10mPath : m_R20mPath);
        const std::string file =
            m_FilePrefix + "_" + normalizedBand + "_" + std::to_string(res) + "m.jp2";
        return joinPath(dir, file);
    }

    std::string BuildSclPath() const
    {
        const std::string file = m_FilePrefix + "_SCL_20m.jp2";
        return joinPath(m_R20mPath, file);
    }

    std::string m_MtdPath;
    std::string m_ProductRoot;
    std::string m_GranuleName;
    std::string m_GranulePath;
    std::string m_R10mPath;
    std::string m_R20mPath;
    std::string m_AcquisitionDateTime;
    std::string m_FilePrefix;
    std::map<int, float> m_BoaOffsetsByBandId;
};

class MajaProduct : public Sentinel2Product
{
public:
    MajaProduct(const std::string &mtdPath,
                const std::string &productRoot,
                const std::string &filePrefix,
                const std::string &acquisitionDateTime)
        : m_MtdPath(mtdPath),
          m_ProductRoot(productRoot),
          m_FilePrefix(filePrefix),
          m_AcquisitionDateTime(acquisitionDateTime)
    {
    }

    std::string GetBandPath(Sentinel2Band band) const override
    {
        const std::string normalizedBand = GetBandToken(band);
        return (fs::path(m_ProductRoot) / (m_FilePrefix + "_FRE_" + normalizedBand + ".tif"))
            .string();
    }

    std::string GetAcquisitionDateYYYYMMDD() const override
    {
        return firstEightDigits(m_AcquisitionDateTime);
    }

    float GetBandOffset(Sentinel2Band band) const override { return 0.0f; }

    itk::ProcessObject::Pointer BuildMask(int targetPixelSizeMeters,
                                          std::vector<UInt8ImageReaderType::Pointer> &readers,
                                          std::vector<UInt8ScalarResampleType::Pointer> &resamplers,
                                          UInt8ImageType::Pointer &outMask) const override
    {
        const std::string suffix = (targetPixelSizeMeters == 10) ? "_R1.tif" : "_R2.tif";
        const std::string maskDir = (fs::path(m_ProductRoot) / "MASKS").string();

        const std::string mg2Path = joinPath(maskDir, m_FilePrefix + "_MG2" + suffix);
        const std::string edgPath = joinPath(maskDir, m_FilePrefix + "_EDG" + suffix);
        const std::string satPath = joinPath(maskDir, m_FilePrefix + "_SAT" + suffix);

        auto mg2Reader = UInt8ImageReaderType::New();
        mg2Reader->SetFileName(mg2Path);
        auto mg2Img = mg2Reader->GetOutput();
        mg2Img->UpdateOutputInformation();
        readers.push_back(mg2Reader);

        auto edgReader = UInt8ImageReaderType::New();
        edgReader->SetFileName(edgPath);
        auto edgImg = edgReader->GetOutput();
        edgImg->UpdateOutputInformation();
        readers.push_back(edgReader);

        auto satReader = UInt8ImageReaderType::New();
        satReader->SetFileName(satPath);
        auto satImage = satReader->GetOutput();
        satImage->UpdateOutputInformation();
        readers.push_back(satReader);

        auto filter = otb::NewFunctorFilter([](uint8_t mg2, uint8_t edg, uint8_t sat) -> uint8_t {
            return (edg != 0 || sat != 0 || (mg2 & 0x0F) != 0) ? 1 : 0;
        });
        filter->SetInputs(mg2Img, edgImg, satImage);
        outMask = filter->GetOutput();
        return filter.GetPointer();
    }

    int GetBandNativeResolution(Sentinel2Band band) const
    {
        switch (band) {
            case Sentinel2Band::B11:
            case Sentinel2Band::B12:
            case Sentinel2Band::B8A:
            case Sentinel2Band::B5:
            case Sentinel2Band::B6:
            case Sentinel2Band::B7:
                return 20;
            default:
                return 10;
        }
    }

    std::string GetBandToken(Sentinel2Band band) const
    {
        switch (band) {
            case Sentinel2Band::B2:
                return "B2";
            case Sentinel2Band::B3:
                return "B3";
            case Sentinel2Band::B4:
                return "B4";
            case Sentinel2Band::B8:
                return "B8";
            case Sentinel2Band::B11:
                return "B11";
            case Sentinel2Band::B12:
                return "B12";
            case Sentinel2Band::B8A:
                return "B8A";
            case Sentinel2Band::B5:
                return "B5";
            case Sentinel2Band::B6:
                return "B6";
            case Sentinel2Band::B7:
                return "B7";
        }
        itkGenericExceptionMacro("Unsupported Sentinel2Band enum value");
    }

    std::string m_MtdPath;
    std::string m_ProductRoot;
    std::string m_FilePrefix;
    std::string m_AcquisitionDateTime;
};

class ProductReader
{
public:
    std::unique_ptr<Sentinel2Product> Read(const std::string &mtdPath) const
    {
        const fs::path mtdFsPath(mtdPath);
        const fs::path productRootPath = mtdFsPath.parent_path();
        const fs::path granuleRootPath = productRootPath / "GRANULE";

        const std::string productRoot = productRootPath.string();
        const std::string granuleRoot = granuleRootPath.string();

        std::string granuleName;
        std::error_code ec;
        fs::directory_iterator it(granuleRoot, ec);
        fs::directory_iterator end;
        if (!ec) {
            for (; it != end; it.increment(ec)) {
                if (ec) {
                    continue;
                }
                if (!fs::is_directory(*it, ec)) {
                    continue;
                }
                const std::string name = it->path().filename().string();
                if (name.starts_with("L2A_")) {
                    granuleName = name;
                    break;
                }
            }
        }

        if (!granuleName.empty()) {
            const std::string safeName = productRootPath.filename().string();
            const std::string safeStem = safeName.substr(0, safeName.find(".SAFE"));
            const auto safeParts = splitString(safeStem, '_');
            if (safeParts.size() < 7) {
                itkGenericExceptionMacro("Invalid SAFE product name: " + safeName);
            }
            const std::string tileId = safeParts[5];
            const std::string sensingDateTime = safeParts[2];
            const std::string filePrefix = tileId + "_" + sensingDateTime;

            const auto boaOffsetsByBandId = ReadBoaOffsetsByBandId(mtdPath);

            return std::unique_ptr<Sentinel2Product>(
                new Sen2CorProduct(mtdPath, productRoot, granuleName, filePrefix, sensingDateTime,
                                   boaOffsetsByBandId));
        } else {
            const std::string productRoot = productRootPath.string();
            const std::string filename = mtdFsPath.filename().string();
            const size_t pos = filename.find("_MTD_ALL");
            if (pos == std::string::npos) {
                itkGenericExceptionMacro(
                    "Invalid MAJA metadata filename (expected *_MTD_ALL.xml): " + productRoot);
            }
            const std::string filePrefix = filename.substr(0, pos);

            auto parts = splitString(filePrefix, '_');
            if (parts.size() < 2) {
                itkGenericExceptionMacro("Invalid MAJA product prefix: " + filePrefix);
            }
            std::string acquisitionDateTime = parts[1];

            return std::unique_ptr<Sentinel2Product>(
                new MajaProduct(mtdPath, productRoot, filePrefix, acquisitionDateTime));
        }
    }

private:
    void ExtractBoaOffsetsFromNode(const TiXmlNode *node, std::map<int, float> &offsets) const
    {
        if (!node) {
            return;
        }

        for (const TiXmlNode *child = node->FirstChild(); child != nullptr;
             child = child->NextSibling()) {
            const TiXmlElement *element = child->ToElement();
            if (element && std::string(element->Value()) == "BOA_ADD_OFFSET_VALUES_LIST") {
                for (const TiXmlNode *offsetNode = element->FirstChild("BOA_ADD_OFFSET");
                     offsetNode != nullptr;
                     offsetNode = offsetNode->NextSibling("BOA_ADD_OFFSET")) {
                    const TiXmlElement *offsetElement = offsetNode->ToElement();
                    if (!offsetElement) {
                        continue;
                    }

                    const char *bandIdAttr = offsetElement->Attribute("band_id");
                    const char *offsetText = offsetElement->GetText();
                    if (!bandIdAttr || !offsetText) {
                        continue;
                    }

                    const int bandId = std::stoi(bandIdAttr);
                    const float value = std::stof(offsetText);
                    offsets[bandId] = value;
                }
            }

            ExtractBoaOffsetsFromNode(child, offsets);
        }
    }

    std::map<int, float> ReadBoaOffsetsByBandId(const std::string &mtdPath) const
    {
        std::map<int, float> offsets;

        TiXmlDocument xmlDocument(mtdPath.c_str());
        if (!xmlDocument.LoadFile()) {
            return offsets;
        }

        ExtractBoaOffsetsFromNode(&xmlDocument, offsets);

        return offsets;
    }
};

std::string firstEightDigits(const std::string &value)
{
    std::string digits;
    for (char c : value) {
        if (std::isdigit(static_cast<unsigned char>(c))) {
            digits.push_back(c);
            if (digits.size() == 8) {
                return digits;
            }
        }
    }
    return digits;
}

std::vector<SensorPreferences> parseSensorPreferences(const std::vector<std::string> &sp)
{
    std::vector<SensorPreferences> res;
    if (sp.empty()) {
        return res;
    }

    bool hasColonFormat = false;
    for (const auto &item : sp) {
        if (item.find(':') != std::string::npos) {
            hasColonFormat = true;
            break;
        }
    }

    if (hasColonFormat) {
        for (const auto &item : sp) {
            std::stringstream ss(item);
            std::string mission;
            int priority = 0;
            int samplingRate = 0;
            std::getline(ss, mission, ':');
            ss >> priority;
            ss.ignore();
            ss >> samplingRate;
            if (!mission.empty() && samplingRate > 0) {
                res.push_back({ mission, priority, samplingRate });
            }
        }
        return res;
    }

    for (size_t i = 0; i + 1 < sp.size(); i += 2) {
        const std::string &mission = sp[i];
        const int samplingRate = std::stoi(sp[i + 1]);
        if (!mission.empty() && samplingRate > 0) {
            res.push_back({ mission, static_cast<int>(i / 2), samplingRate });
        }
    }

    return res;
}
} // namespace

namespace otb
{
namespace Wrapper
{

class OpticalFeaturesRewrite : public Application
{
public:
    typedef OpticalFeaturesRewrite Self;
    typedef Application Superclass;
    typedef itk::SmartPointer<Self> Pointer;
    typedef itk::SmartPointer<const Self> ConstPointer;

    itkNewMacro(Self);
    itkTypeMacro(OpticalFeaturesRewrite, otb::Application);

    typedef otb::Image<float, 2> FloatImageType;
    typedef otb::VectorImage<float, 2> FloatVectorImageType;
    typedef otb::Image<uint8_t, 2> UInt8ImageType;
    typedef otb::Image<int32_t, 2> Int32ImageType;
    typedef otb::VectorImage<uint8_t, 2> UInt8VectorImageType;
    typedef otb::ImageFileReader<FloatImageType> FloatImageReaderType;
    typedef otb::ImageFileReader<UInt8ImageType> UInt8ImageReaderType;
    typedef itk::IdentityTransform<double, 2> IdentityTransformType;
    typedef otb::StreamingResampleImageFilter<FloatImageType, FloatImageType, double>
        FloatScalarResampleType;
    typedef otb::StreamingResampleImageFilter<UInt8ImageType, UInt8ImageType, double>
        UInt8ScalarResampleType;

    typedef otb::StreamingStatisticsMapFromLabelImageFilter2<FloatVectorImageType, Int32ImageType>
        StatsFilterType;

    typedef otb::
        TemporalResamplingFilter<FloatVectorImageType, UInt8VectorImageType, FloatVectorImageType>
            TemporalResamplingFilterType;
    typedef otb::CropTypeFeatureExtractionFilter<FloatVectorImageType> FeatureExtractionFilterType;

    typedef otb::GenericRSResampleImageFilter<FloatVectorImageType, FloatVectorImageType>
        FloatResamplerType;
    typedef otb::GenericRSResampleImageFilter<UInt8ImageType, UInt8ImageType> UInt8ResamplerType;
    typedef otb::GenericRSResampleImageFilter<Int32ImageType, Int32ImageType> Int32ResamplerType;

    typedef otb::ImageToVectorImageCastFilter<UInt8ImageType, UInt8VectorImageType>
        UInt8ToVectorCastFilterType;
    typedef itk::CastImageFilter<UInt8VectorImageType, FloatVectorImageType>
        UInt8VectorToFloatVectorCastFilterType;
    typedef itk::UnaryFunctorImageFilter<FloatImageType, FloatImageType, AddOffsetFunctor>
        FloatOffsetFilterType;
    typedef otb::ConcatenateVectorImageFilter<FloatVectorImageType,
                                              FloatVectorImageType,
                                              FloatVectorImageType>
        FloatVectorConcatFilterType;
    typedef otb::ConcatenateVectorImageFilter<UInt8VectorImageType,
                                              UInt8VectorImageType,
                                              UInt8VectorImageType>
        UInt8VectorConcatFilterType;

    typedef otb::ImageList<FloatImageType> FloatImageListType;
    typedef otb::ImageList<UInt8ImageType> UInt8ImageListType;
    typedef otb::ImageListToVectorImageFilter<FloatImageListType, FloatVectorImageType>
        FloatConcatFilterType;
    typedef otb::ImageListToVectorImageFilter<UInt8ImageListType, UInt8VectorImageType>
        UInt8ConcatFilterType;

    typedef itk::VectorIndexSelectionCastImageFilter<FloatVectorImageType, FloatImageType>
        FloatExtractFilterType;

private:
    void DoInit() override
    {
        SetName("OpticalFeaturesRewrite");
        SetDescription(
            "Computes NDVI, NDWI, and Brightness features from a time series of S2 descriptors.");

        AddParameter(ParameterType_StringList, "il", "Input metadata files");

        AddParameter(ParameterType_InputImage, "ref", "Reference class image for stats");
        AddParameter(ParameterType_OutputFilename, "outmean", "Output average stats CSV");
        AddParameter(ParameterType_OutputFilename, "outdev", "Output standard deviation CSV");
        AddParameter(ParameterType_OutputFilename, "outcount", "Output pixel count CSV");

        AddParameter(ParameterType_OutputImage, "outgap",
                     "Debug output gap-filled feature stack image (bypasses statistics)");
        MandatoryOff("outgap");

        AddParameter(ParameterType_OutputImage, "outbands",
                     "Debug output pre-gapfill bands stack image");
        MandatoryOff("outbands");

        AddParameter(ParameterType_OutputImage, "outmasks",
                     "Debug output pre-gapfill masks stack image");
        MandatoryOff("outmasks");

        AddParameter(ParameterType_StringList, "sp", "Sampling preferences (MISSION:PRIO:RATE)");
        MandatoryOff("sp");

        AddParameter(ParameterType_Choice, "mode", "Mode");
        SetParameterDescription("mode", "Specifies the choice of output dates (default: resample)");
        AddChoice("mode.resample", "Specifies the temporal resampling mode");
        AddChoice("mode.gapfill", "Specifies the gapfilling mode");
        AddChoice("mode.gapfillmain", "Specifies the gapfilling mode, but only use non-main series "
                                      "products to fill in the main one");
        SetParameterString("mode", "resample");

        AddParameter(ParameterType_InputFilename, "dates", "Sampling dates");
        MandatoryOff("dates");

        AddParameter(ParameterType_OutputFilename, "outdates", "Output sampling dates");
        MandatoryOff("outdates");

        AddParameter(ParameterType_String, "mission",
                     "The main raster series that will be used. By default, SENTINEL is used");
        SetParameterString("mission", "SENTINEL");
        MandatoryOff("mission");

        AddParameter(ParameterType_Bool, "rededge", "Include Sentinel-2 vegetation red edge bands");
        MandatoryOff("rededge");

        AddRAMParameter();
    }

    void DoUpdateParameters() override {}

    FloatImageType::Pointer ResampleScalarToPixelSize(FloatImageType *input,
                                                      FloatScalarResampleType *resampler,
                                                      double targetPixelSizeMeters)
    {
        input->UpdateOutputInformation();
        auto inSpacing = input->GetSignedSpacing();

        FloatImageType::SpacingType outSpacing;
        outSpacing[0] = (inSpacing[0] < 0.0 ? -targetPixelSizeMeters : targetPixelSizeMeters);
        outSpacing[1] = (inSpacing[1] < 0.0 ? -targetPixelSizeMeters : targetPixelSizeMeters);

        itk::FixedArray<double, 2> scale;
        scale[0] = outSpacing[0] / inSpacing[0];
        scale[1] = outSpacing[1] / inSpacing[1];

        auto inOrigin = input->GetOrigin();
        FloatImageType::PointType outOrigin;
        outOrigin[0] = inOrigin[0] + 0.5 * inSpacing[0] * (scale[0] - 1.0);
        outOrigin[1] = inOrigin[1] + 0.5 * inSpacing[1] * (scale[1] - 1.0);

        auto inSize = input->GetLargestPossibleRegion().GetSize();
        FloatScalarResampleType::SizeType outSize;
        outSize[0] = static_cast<unsigned int>(std::round(inSize[0] / scale[0]));
        outSize[1] = static_cast<unsigned int>(std::round(inSize[1] / scale[1]));

        auto interp = otb::BCOInterpolateImageFunction<FloatImageType, double>::New();
        interp->SetRadius(kReflectanceBCORadius);
        interp->SetAlpha(kReflectanceBCOAlpha);
        auto transform = IdentityTransformType::New();
        resampler->SetInput(input);
        resampler->SetInterpolator(interp);
        resampler->SetTransform(transform);
        resampler->SetOutputStartIndex(input->GetLargestPossibleRegion().GetIndex());
        resampler->SetOutputSpacing(outSpacing);
        resampler->SetOutputOrigin(outOrigin);
        resampler->SetOutputSize(outSize);
        resampler->SetEdgePaddingValue(-10000.0f);

        return resampler->GetOutput();
    }

    void DoExecute() override
    {
        auto inputList = GetParameterStringList("il");
        auto spList = GetParameterStringList("sp");
        const bool redEdge = GetParameterInt("rededge") != 0;
        const double targetPixelSizeMeters = redEdge ? 20.0 : 10.0;
        const std::string mainMission = GetParameterString("mission");

        TemporalResamplingMode resamplingMode = TemporalResamplingMode::Resample;
        const std::string modeStr = GetParameterString("mode");
        if (modeStr == "gapfill") {
            resamplingMode = TemporalResamplingMode::GapFill;
        } else if (modeStr == "gapfillmain") {
            resamplingMode = TemporalResamplingMode::GapFillMainMission;
        }

        std::map<std::string, std::vector<int>> explicitDates;
        if (HasValue("dates")) {
            std::ifstream datesFile(GetParameterString("dates"));
            std::string line;
            while (std::getline(datesFile, line)) {
                if (line.empty())
                    continue;
                std::stringstream ss(line);
                std::string token1;
                int token2;
                ss >> token1;
                if (ss >> token2) {
                    explicitDates[token1].push_back(token2);
                } else {
                    explicitDates[""].push_back(std::stoi(token1));
                }
            }
        }

        if (inputList.empty()) {
            itkExceptionMacro("Input list is empty.");
        }

        std::vector<SensorPreferences> spRef = parseSensorPreferences(spList);
        if (spRef.empty()) {
            spRef.push_back({ "SENTINEL", 0, 10 });
            spRef.push_back({ "SPOT", 1, 5 });
            spRef.push_back({ "LANDSAT", 2, 16 });
        }
        std::map<std::string, SensorPreferences> spMap;
        for (const auto &sp : spRef) {
            spMap[sp.mission] = sp;
        }

        struct InputImageInfo {
            std::string filename;
            std::string mission;
            int dateDays;
            std::vector<FloatImageType::Pointer> bandImages;
            UInt8ImageType::Pointer mask;
        };

        std::vector<InputImageInfo> imageInfos;
        std::map<std::string, unsigned int> sensorBandCount;
        std::vector<FloatImageReaderType::Pointer> floatReaders;
        std::vector<UInt8ImageReaderType::Pointer> uInt8Readers;
        std::vector<FloatOffsetFilterType::Pointer> bandOffsetFilters;
        std::vector<FloatScalarResampleType::Pointer> floatScalarResamplers;
        std::vector<UInt8ScalarResampleType::Pointer> uInt8ScalarResamplers;
        std::vector<itk::ProcessObject::Pointer> sclMaskFilters;

        for (const auto &f : inputList) {
            ProductReader productReader;
            std::unique_ptr<Sentinel2Product> product = productReader.Read(f);
            std::vector<Sentinel2Band> selectedBands;
            if (redEdge) {
                selectedBands = { Sentinel2Band::B5, Sentinel2Band::B6, Sentinel2Band::B7,
                                  Sentinel2Band::B12 };
            } else {
                selectedBands = { Sentinel2Band::B3, Sentinel2Band::B4, Sentinel2Band::B8,
                                  Sentinel2Band::B11 };
            }
            std::vector<FloatImageType::Pointer> productBands;
            FloatImageType::Pointer firstBandRef;

            for (const auto band : selectedBands) {
                const std::string bandPath = product->GetBandPath(band);

                auto bandReader = FloatImageReaderType::New();
                bandReader->SetFileName(bandPath);
                auto bandImage = bandReader->GetOutput();
                bandImage->UpdateOutputInformation();
                floatReaders.push_back(bandReader);

                FloatImageType::Pointer adjustedBand = bandImage;
                const float bandOffset = product->GetBandOffset(band);
                if (bandOffset) {
                    auto bandOffsetFilter = FloatOffsetFilterType::New();
                    bandOffsetFilter->SetInput(bandImage);
                    bandOffsetFilter->GetFunctor().SetOffset(bandOffset);
                    adjustedBand = bandOffsetFilter->GetOutput();
                    adjustedBand->UpdateOutputInformation();
                    bandOffsetFilters.push_back(bandOffsetFilter);
                }

                if (!firstBandRef) {
                    firstBandRef = adjustedBand;
                }

                FloatImageType::Pointer bandForConcat = adjustedBand;
                const double bandSpacing = std::abs(bandImage->GetSignedSpacing()[0]);
                if (bandSpacing != targetPixelSizeMeters) {
                    auto toPixResampler = FloatScalarResampleType::New();
                    bandForConcat = ResampleScalarToPixelSize(adjustedBand, toPixResampler,
                                                              targetPixelSizeMeters);
                    floatScalarResamplers.push_back(toPixResampler);
                    bandForConcat->UpdateOutputInformation();
                }

                productBands.push_back(bandForConcat);
            }

            UInt8ImageType::Pointer mask;
            auto sclToMask = product->BuildMask(static_cast<int>(targetPixelSizeMeters),
                                                uInt8Readers, uInt8ScalarResamplers, mask);

            const std::string dateStr = product->GetAcquisitionDateYYYYMMDD();
            const std::string mission = "SENTINEL";
            const int days = getDaysFromEpoch(dateStr);

            imageInfos.push_back({ f, mission, days, productBands, mask });

            sclMaskFilters.push_back(sclToMask);
        }

        std::sort(imageInfos.begin(), imageInfos.end(),
                  [](const InputImageInfo &a, const InputImageInfo &b) {
                      if (a.dateDays != b.dateDays) {
                          return a.dateDays < b.dateDays;
                      }
                      return a.filename < b.filename;
                  });

        auto classImg = GetParameterInt32Image("ref");
        classImg->UpdateOutputInformation();

        std::map<std::string, std::set<int>> sensorInDays;
        std::map<std::string, std::vector<std::pair<int, std::vector<FloatImageType::Pointer>>>>
            missionImages;
        std::map<std::string, std::vector<std::pair<int, UInt8ImageType::Pointer>>> missionMasks;

        for (const auto &info : imageInfos) {
            sensorInDays[info.mission].insert(info.dateDays);

            auto mask = info.mask;
            mask->UpdateOutputInformation();

            auto missionBandIt = sensorBandCount.find(info.mission);
            if (missionBandIt == sensorBandCount.end()) {
                sensorBandCount[info.mission] = static_cast<unsigned int>(info.bandImages.size());
            } else if (missionBandIt->second != info.bandImages.size()) {
                itkExceptionMacro("Inconsistent number of bands for mission "
                                  << info.mission << ": expected " << missionBandIt->second
                                  << " but got " << info.bandImages.size() << " for "
                                  << info.filename);
            }

            missionImages[info.mission].push_back({ info.dateDays, info.bandImages });
            missionMasks[info.mission].push_back({ info.dateDays, mask });
        }

        SensorDataCollection sdc;

        std::vector<int> mainMissionDays;
        if (resamplingMode == TemporalResamplingMode::GapFillMainMission) {
            const auto mainIt = sensorInDays.find(mainMission);
            if (mainIt == sensorInDays.end()) {
                itkExceptionMacro(
                    "Main mission not found in inputs for gapfillmain mode: " << mainMission);
            }
            mainMissionDays.assign(mainIt->second.begin(), mainIt->second.end());
        }

        for (const auto &sensorPair : sensorInDays) {
            SensorData sd;
            sd.sensorName = sensorPair.first;
            auto bandCountIt = sensorBandCount.find(sensorPair.first);
            if (bandCountIt == sensorBandCount.end()) {
                itkExceptionMacro("Missing band count for mission " << sensorPair.first);
            }
            sd.bandCount = static_cast<int>(bandCountIt->second);

            const auto missionImagesIt = missionImages.find(sensorPair.first);
            if (missionImagesIt == missionImages.end()) {
                itkExceptionMacro("Missing mission image list for sensor " << sensorPair.first);
            }
            for (const auto &entry : missionImagesIt->second) {
                sd.inDates.push_back(entry.first);
            }

            if (HasValue("dates")) {
                if (explicitDates.count(sensorPair.first)) {
                    sd.outDates = explicitDates[sensorPair.first];
                } else if (!explicitDates[""].empty()) {
                    sd.outDates = explicitDates[""];
                } else {
                    sd.outDates = sd.inDates;
                }
            } else {
                if (resamplingMode == TemporalResamplingMode::Resample) {
                    auto it = spMap.find(sensorPair.first);
                    if (it == spMap.end()) {
                        itkExceptionMacro("Sampling rate required for sensor " << sensorPair.first);
                    }
                    int rate = it->second.samplingRate;
                    int firstDate = sd.inDates.front();
                    int lastDate = sd.inDates.back();
                    for (int d = firstDate; d <= lastDate; d += rate) {
                        sd.outDates.push_back(d);
                    }
                } else if (resamplingMode == TemporalResamplingMode::GapFill) {
                    sd.outDates = sd.inDates;
                } else if (resamplingMode == TemporalResamplingMode::GapFillMainMission) {
                    sd.outDates = mainMissionDays;
                } else {
                    sd.outDates = sd.inDates;
                }
            }
            sdc.push_back(sd);
        }

        if (HasValue("outdates")) {
            std::ofstream f(GetParameterString("outdates"));
            for (const auto &sd : sdc) {
                for (int d : sd.outDates) {
                    f << sd.sensorName << " " << d << "\n";
                }
            }
        }

        if (!spMap.empty()) {
            std::sort(sdc.begin(), sdc.end(), [&spMap](const SensorData &a, const SensorData &b) {
                return spMap[a.sensorName].priority < spMap[b.sensorName].priority;
            });
        }

        for (auto &pair : missionImages) {
            auto &entries = pair.second;
            std::stable_sort(entries.begin(), entries.end(),
                             [](const auto &a, const auto &b) { return a.first < b.first; });
        }
        for (auto &pair : missionMasks) {
            auto &entries = pair.second;
            std::stable_sort(entries.begin(), entries.end(),
                             [](const auto &a, const auto &b) { return a.first < b.first; });
        }

        FloatVectorImageType::Pointer orderedBands;
        UInt8VectorImageType::Pointer orderedMasks;

        m_FloatImageList = FloatImageListType::New();
        m_UInt8ImageList = UInt8ImageListType::New();

        for (const auto &sd : sdc) {
            auto imgIt = missionImages.find(sd.sensorName);
            auto maskIt = missionMasks.find(sd.sensorName);
            if (imgIt == missionImages.end() || maskIt == missionMasks.end()) {
                itkExceptionMacro("Missing mission data for sensor " << sd.sensorName);
            }
            if (imgIt->second.size() != maskIt->second.size()) {
                itkExceptionMacro("Image/mask count mismatch for sensor " << sd.sensorName);
            }

            for (size_t i = 0; i < imgIt->second.size(); ++i) {
                const auto &productBands = imgIt->second[i].second;
                auto maskOut = maskIt->second[i].second;

                for (const auto &bImg : productBands) {
                    bImg->UpdateOutputInformation();
                    m_FloatImageList->PushBack(bImg);
                }

                maskOut->UpdateOutputInformation();
                m_UInt8ImageList->PushBack(maskOut);
            }
        }

        if (m_FloatImageList->Size() == 0 || m_UInt8ImageList->Size() == 0) {
            itkExceptionMacro("No valid temporal stack built from inputs");
        }

        m_BandsConcat = FloatConcatFilterType::New();
        m_BandsConcat->SetInput(m_FloatImageList);
        orderedBands = m_BandsConcat->GetOutput();

        m_MaskConcat = UInt8ConcatFilterType::New();
        m_MaskConcat->SetInput(m_UInt8ImageList);
        orderedMasks = m_MaskConcat->GetOutput();

        if (!orderedBands || !orderedMasks) {
            itkExceptionMacro("No valid temporal stack built from inputs");
        }

        orderedBands->UpdateOutputInformation();
        orderedMasks->UpdateOutputInformation();
        const auto refRegion = orderedBands->GetLargestPossibleRegion();

        auto temporalResampler = TemporalResamplingFilterType::New();
        temporalResampler->SetInputRaster(orderedBands);
        temporalResampler->SetInputMask(orderedMasks);
        temporalResampler->SetInputData(sdc);
        temporalResampler->UpdateOutputInformation();

        auto featureExtractor = FeatureExtractionFilterType::New();
        FloatVectorImageType::Pointer analysisOutput;
        if (redEdge) {
            analysisOutput = temporalResampler->GetOutput();
            analysisOutput->UpdateOutputInformation();
        } else {
            featureExtractor->SetInput(temporalResampler->GetOutput());
            featureExtractor->SetSensorData(sdc);
            featureExtractor->UpdateOutputInformation();
            analysisOutput = featureExtractor->GetOutput();
        }

        m_GapFillProcess = temporalResampler;

        if (HasValue("outbands")) {
            SetParameterOutputImage("outbands", orderedBands);
            SetParameterOutputImagePixelType("outbands", ImagePixelType_float);
        }

        if (HasValue("outmasks")) {
            auto maskFloatCast = UInt8VectorToFloatVectorCastFilterType::New();
            maskFloatCast->SetInput(orderedMasks);
            m_MaskFloatCast = maskFloatCast;
            SetParameterOutputImage("outmasks", m_MaskFloatCast->GetOutput());
            SetParameterOutputImagePixelType("outmasks", ImagePixelType_float);
        }

        if (HasValue("outgap")) {
            SetParameterOutputImage("outgap", analysisOutput);
            SetParameterOutputImagePixelType("outgap", ImagePixelType_float);
            otbAppLogINFO("Debug mode enabled via outgap: skipping statistics computation.");
            return;
        }

        Int32ImageType::Pointer classForStats = classImg;
        classImg->UpdateOutputInformation();

        m_StatsFilter = StatsFilterType::New();
        m_StatsFilter->SetInput(analysisOutput);
        m_StatsFilter->SetInputLabelImage(classForStats);
        m_StatsFilter->SetNoDataValue(-10000);
        m_StatsFilter->SetUseNoDataValue(true);
        m_StatsFilter->GetStreamer()->SetTileDimensionTiledStreaming(2048);

        AddProcess(m_StatsFilter->GetStreamer(), "Computing features...");

        m_StatsFilter->Update();

        otbAppLogINFO("Statistical extraction completed.");

        std::ofstream meanFile(GetParameterString("outmean"));
        std::ofstream devFile(GetParameterString("outdev"));
        std::ofstream countFile(GetParameterString("outcount"));

        const auto outmean = GetParameterString("outmean");
        const auto outdev = GetParameterString("outdev");
        const auto outcount = GetParameterString("outcount");

        const auto &meanValues = m_StatsFilter->GetMeanValueMap();
        const auto &stdDevValues = m_StatsFilter->GetStandardDeviationValueMap();
        const auto &countValues = m_StatsFilter->GetPixelCountMap();

        for (const auto &pair : meanValues) {
            meanFile << pair.first;
            for (unsigned int i = 0; i < pair.second.Size(); ++i) {
                meanFile << "," << pair.second[i];
            }
            meanFile << "\n";
        }
        meanFile.close();
        if (!meanFile) {
            itkGenericExceptionMacro("Unable to save " + outmean);
        }

        for (const auto &pair : stdDevValues) {
            devFile << pair.first;
            for (unsigned int i = 0; i < pair.second.Size(); ++i) {
                devFile << "," << pair.second[i];
            }
            devFile << "\n";
        }
        devFile.close();
        if (!devFile) {
            itkGenericExceptionMacro("Unable to save " + outdev);
        }

        for (const auto &pair : countValues) {
            countFile << pair.first;
            for (unsigned int i = 0; i < pair.second.Size(); ++i) {
                countFile << "," << pair.second[i];
            }
            countFile << "\n";
        }
        countFile.close();
        if (!countFile) {
            itkGenericExceptionMacro("Unable to save " + outcount);
        }
    }

    FloatImageListType::Pointer m_FloatImageList;
    UInt8ImageListType::Pointer m_UInt8ImageList;
    FloatConcatFilterType::Pointer m_BandsConcat;
    UInt8ConcatFilterType::Pointer m_MaskConcat;

    UInt8VectorToFloatVectorCastFilterType::Pointer m_MaskFloatCast;
    itk::ProcessObject::Pointer m_GapFillProcess;

    StatsFilterType::Pointer m_StatsFilter;
};

} // namespace Wrapper
} // namespace otb

OTB_APPLICATION_EXPORT(otb::Wrapper::OpticalFeaturesRewrite)
