/*=========================================================================
  *
  * Program:      Sen2agri-Processors
  * Language:     C++
  * Copyright:    2015-2016, CS Romania, office@c-s.ro
  * See COPYRIGHT file for details.
  *
  * Unless required by applicable law or agreed to in writing, software
  * distributed under the License is distributed on an "AS IS" BASIS,
  * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  * See the License for the specific language governing permissions and
  * limitations under the License.

 =========================================================================*/
 
#include "otbExtendedFilenameHelper.h"
#include "otbWrapperApplication.h"
#include "otbWrapperApplicationFactory.h"

#include <memory>
#include "MetadataHelperFactory.h"
#include "otbStreamingResampleImageFilter.h"
#include "ImageResampler.h"

namespace otb
{

namespace Wrapper
{

class GenerateLaiMonoDateMaskFlags : public Application
{
public:    

    typedef GenerateLaiMonoDateMaskFlags Self;
    typedef Application Superclass;
    typedef itk::SmartPointer<Self> Pointer;
    typedef itk::SmartPointer<const Self> ConstPointer;
    itkNewMacro(Self)

    itkTypeMacro(GenerateLaiMonoDateMaskFlags, otb::Application)

    typedef otb::StreamingResampleImageFilter<MetadataHelper<short>::SingleBandShortImageType,
                    MetadataHelper<short>::SingleBandShortImageType, double>     ResampleFilterType;

private:
    void DoInit()
    {
        SetName("GenerateLaiMonoDateMaskFlags");
        SetDescription("Extracts the flag masks for the given product.");

        SetDocLongDescription("long description");
        SetDocLimitations("None");
        SetDocAuthors("CIU");
        SetDocSeeAlso(" ");        
        AddDocTag(Tags::Vector);
        AddParameter(ParameterType_String,  "xml",   "Input XML corresponding to the LAI mono date");
        AddParameter(ParameterType_String,  "extmsk",   "Input external mask corresponding to the input L2A product");
        MandatoryOff("extmsk");

        AddParameter(ParameterType_OutputImage,  "out",   "The out mask flags image corresponding to the LAI mono date");
        SetDefaultOutputPixelType("out", ImagePixelType_uint8);
        AddParameter(ParameterType_Int, "compress", "If set to a value different of 0, the output is compressed");
        MandatoryOff("compress");
        SetDefaultParameterInt("compress", 0);

        AddParameter(ParameterType_Int, "cog", "If set to a value different of 0, the output is created in cloud optimized geotiff and compressed.");
        MandatoryOff("cog");
        SetDefaultParameterInt("cog", 0);

        AddParameter(ParameterType_Int, "outres", "Output resolution. If not specified, is the same as the input resolution.");
        MandatoryOff("outres");
        AddParameter(ParameterType_OutputImage,  "outresampled",   "The out mask flags image corresponding to the LAI mono date resampled at the given resolution");
        MandatoryOff("outresampled");
        SetDefaultOutputPixelType("outresampled", ImagePixelType_uint8);
    }

    void DoUpdateParameters()
    {
      // Nothing to do.
    }

    void DoExecute()
    {
        const std::string &inXml = GetParameterAsString("xml");
        std::string extMsk;
        if (HasValue("extmsk")) {
            extMsk = GetParameterAsString("extmsk");
        }

        auto factory = MetadataHelperFactory::New();
        std::unique_ptr<MetadataHelper<short>> pHelper = factory->GetMetadataHelper<short>(inXml, extMsk);
        MetadataHelper<short>::SingleBandMasksImageType::Pointer imgMsk = pHelper->GetMasksImage(ALL, false);

        ConfigureOutput("out", imgMsk);

        if(HasValue("outres")) {
            if(HasValue("outresampled")) {
                int nOutRes = GetParameterInt("outres");
                if(nOutRes != 10 && nOutRes != 20) {
                    itkExceptionMacro("Invalid output resolution specified (only 10 and 20 accepted)" << nOutRes);
                }
                imgMsk->UpdateOutputInformation();
                int curRes = imgMsk->GetSpacing()[0];
                ConfigureOutput("outresampled", getResampledImage(curRes, nOutRes, imgMsk));
            } else {
                itkExceptionMacro("If you provide the outres parameter you must also provide an outresampled file name!");
            }
        } else {
            DisableParameter("outresampled");
        }
        RegisterPipeline();
    }

    void ConfigureOutput(const std::string &key,
                         MetadataHelper<short>::SingleBandShortImageType::Pointer image)
    {
        SetParameterOutputImage(key, image.GetPointer());
        std::string fileName = GetParameterString(key);
        if (fileName.empty()) {
            return;
        }
        auto filenameHelper = otb::ExtendedFilenameHelper::New();
        filenameHelper->SetExtendedFileName(fileName);

        auto options = filenameHelper->GetOptionMap();
        // Prevent a crash in OTB's adaptive splitter when using ?box
        options.emplace("streaming:type", "tiled");
        if (GetParameterInt("cog") != 0) {
            options.emplace("gdal:co:TILED", "YES");
            options.emplace("gdal:co:COPY_SRC_OVERVIEWS", "YES");
        }
        if (GetParameterInt("cog") != 0 || GetParameterInt("compress") != 0) {
            options.emplace("gdal:co:COMPRESS", "DEFLATE");
        }

        fileName = filenameHelper->GetSimpleFileName();
        fileName += '?';
        for (const auto &option : options) {
            fileName += '&' + option.first + '=' + option.second;
        }
        SetParameterString(key, fileName, false);
    }

    MetadataHelper<short>::SingleBandShortImageType::Pointer getResampledImage(int nCurRes, int nDesiredRes,
                                                 MetadataHelper<short>::SingleBandShortImageType::Pointer inImg) {
        if(nCurRes == nDesiredRes)
            return inImg;
        float fMultiplicationFactor = ((float)nCurRes)/nDesiredRes;
        ResampleFilterType::Pointer resampler = m_Resampler.getResampler(inImg, fMultiplicationFactor, Interpolator_NNeighbor);
        return resampler->GetOutput();
    }

private:
    ImageResampler<MetadataHelper<short>::SingleBandShortImageType, MetadataHelper<short>::SingleBandShortImageType> m_Resampler;

};

}
}
OTB_APPLICATION_EXPORT(otb::Wrapper::GenerateLaiMonoDateMaskFlags)



