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

#include "otbWrapperApplication.h"
#include "otbWrapperApplicationFactory.h"
#include "otbVectorImage.h"
#include "otbVectorImageToImageListFilter.h"
#include "otbImageListToVectorImageFilter.h"
#include "otbStreamingResampleImageFilter.h"
#include "MetadataHelperFactory.h"
#include "ImageResampler.h"
#include "otbMetaDataKey.h"

//Transform
#include "itkScalableAffineTransform.h"
#include "GlobalDefs.h"
#include "itkBinaryFunctorImageFilter.h"
#include "CommonFunctions.h"

namespace otb
{

template< class TInput, class TInput2, class TOutput>
class AnglesMaskingFunctor
{
public:
    AnglesMaskingFunctor() {
        m_MskValidDataValue = 0;
        m_UseMskValidDataValue = false;
    }
    ~AnglesMaskingFunctor() {}

  void SetMskValidDataValue(float val) { m_MskValidDataValue = val; }
  void SetUseMskValidDataValue(bool val) { m_UseMskValidDataValue = val; }
  void SetInvaliDataValues(std::vector<float> val) { m_InvalidDataValues = val; }
  void SetOutNoDataValue(float val) { m_OutNoDataValue = val; }

  bool operator!=( const AnglesMaskingFunctor &a) const
  {
      return false;
  }
  bool operator==( const AnglesMaskingFunctor & other ) const
  {
    return !(*this != other);
  }

  bool isInSet(float value) const {
      return std::binary_search(m_InvalidDataValues.begin(), m_InvalidDataValues.end(), value);
  }

  inline TOutput operator()( const TInput & A, const TInput2 & B ) const
  {
        TOutput ret(A.GetSize());
        for (int i = 0; i<A.GetSize(); i++) {
            ret[i] = A[i];
            if (isInSet(B[i])) {
                ret[i] = m_OutNoDataValue;
            } else {
                if (m_UseMskValidDataValue && B[i] != m_MskValidDataValue) {
                    ret[i] = m_OutNoDataValue;
                }
            }
        }
        return ret;
  }

private:
      float               m_MskValidDataValue;
      bool                m_UseMskValidDataValue;
      std::vector<float>   m_InvalidDataValues;
      float               m_OutNoDataValue;
};

namespace Wrapper
{
class ApplyMaskToRaster : public Application
{
public:
    typedef ApplyMaskToRaster Self;
    typedef Application Superclass;
    typedef itk::SmartPointer<Self> Pointer;
    typedef itk::SmartPointer<const Self> ConstPointer;
    itkNewMacro(Self)

    itkTypeMacro(ApplyMaskToRaster, otb::Application)

    typedef short                                                             PixelType;
    //typedef otb::VectorImage<PixelType, 2>                                    ImageType;
    typedef FloatVectorImageType                                              ImageType;
    //typedef otb::ImageFileReader<ImageType>                                   ReaderType;
    typedef FloatVectorImageType                                              AnglesImageType;

    //typedef otb::ChangeNoDataValueFilter<FloatVectorImageType,FloatVectorImageType> ChangeNoDataFilterType;
    typedef otb::ImageFileReader<ImageType>                              ReaderType;
    typedef otb::ObjectList<ReaderType>                                  ReaderListType;

    typedef itk::BinaryFunctorImageFilter<AnglesImageType,AnglesImageType,AnglesImageType,
                    AnglesMaskingFunctor<
                        AnglesImageType::PixelType, AnglesImageType::PixelType,
                        AnglesImageType::PixelType> > AnglesMaskedOutputFilterType;
private:

    void DoInit()
    {

        SetName("ApplyMaskToRaster");
        SetDescription("Apply the mask over the angles from the product validity mask");

        SetDocName("ApplyMaskToRaster");
        SetDocLongDescription("long description");
        SetDocLimitations("None");
        SetDocAuthors("Cosmin Udroiu");
        SetDocSeeAlso(" ");
        AddDocTag(Tags::Vector);

        AddParameter(ParameterType_String, "input", "Input raster File");
        AddParameter(ParameterType_String, "msk", "Input mask image");

        AddParameter(ParameterType_Float, "mskvld", "Mask valid value");
        SetParameterDescription("mskvld", "Mask valid value for which the input values are considered.");
        SetDefaultParameterFloat("mskvld", 0.);
        MandatoryOff("mskvld");

        AddParameter(ParameterType_Float, "outnodata", "Output no data value");
        SetParameterDescription("outnodata", "Output no data value.");
        SetDefaultParameterFloat("outnodata", -10000);
        MandatoryOff("outnodata");

        AddParameter(ParameterType_String, "mskinvalidvalues", "Mask invalid values list, comma separated");
        MandatoryOff("mskinvalidvalues");

        AddParameter(ParameterType_OutputImage, "out", "Out image");

        SetDocExampleParameterValue("xml", "The product metadata file");
        SetDocExampleParameterValue("out", "/path/to/output_image.tif");
    }

    void DoUpdateParameters()
    {
      // Nothing to do.
    }

    void DoExecute()
    {
        const std::string &inAnglesFile = GetParameterString("input");
        if (inAnglesFile.empty())
        {
            itkExceptionMacro("No input metadata XML set...; please set the input image");
        }
        const std::string &mskFile = GetParameterString("msk");
        if (mskFile.empty())
        {
            itkExceptionMacro("No mask input provided...; please provide the mask");
        }

        auto anglesReader = GetReader(inAnglesFile);
        const auto anglesImage = anglesReader->GetOutput();

        auto mskReader = GetReader(mskFile);
        m_mskImg = mskReader->GetOutput();

        const auto resampledAnglesImage = ResampleAnglesImage(anglesImage);

        SetParameterOutputImagePixelType("out", ImagePixelType_int16);
        SetParameterOutputImage("out", resampledAnglesImage);
    }

    /**
     * Resamples an image according to the given current and desired resolution
     */
    AnglesImageType::Pointer ResampleAnglesImage(AnglesImageType::Pointer anglesRaster) {
        float mskValidValue = GetParameterFloat("mskvld");
        float outNoDataValue = GetParameterFloat("outnodata");
        const std::string &str = GetParameterString("mskinvalidvalues");
        std::istringstream iss(str);
        std::vector<float> mskInvalidValues;
        float val;
        while (iss >> val) {
            mskInvalidValues.push_back(val);
            if (iss.peek() == ',' || iss.peek() == ';')
                iss.ignore();
        }


        auto sz = m_mskImg->GetLargestPossibleRegion().GetSize();
        int width = sz[0];
        int height = sz[1];

        AnglesImageType::Pointer anglesImg = m_AnglesResampler.getResampler(anglesRaster, 1, width, height, m_mskImg->GetOrigin())->GetOutput();
        anglesImg->UpdateOutputInformation();
        m_AnglesMaskedOutputFunctor = AnglesMaskedOutputFilterType::New();
        m_AnglesMaskedOutputFunctor->GetFunctor().SetMskValidDataValue(mskValidValue);
        m_AnglesMaskedOutputFunctor->GetFunctor().SetUseMskValidDataValue(mskInvalidValues.size() == 0);
        m_AnglesMaskedOutputFunctor->GetFunctor().SetInvaliDataValues(mskInvalidValues);
        m_AnglesMaskedOutputFunctor->GetFunctor().SetOutNoDataValue(outNoDataValue);

        AnglesImageType::Pointer retImg = MaskAngles(anglesImg, m_mskImg, m_AnglesMaskedOutputFunctor);
        retImg->UpdateOutputInformation();

        return retImg;
    }

    AnglesImageType::Pointer MaskAngles(AnglesImageType::Pointer anglesImg, AnglesImageType::Pointer msksImg,
                                     AnglesMaskedOutputFilterType::Pointer maskingFunctor) {

        anglesImg->UpdateOutputInformation();
        msksImg->UpdateOutputInformation();

        maskingFunctor->SetInput1(anglesImg);
        maskingFunctor->SetInput2(msksImg);
        return maskingFunctor->GetOutput();
    }

    ReaderType::Pointer GetReader(const std::string &inFile) {
        if (m_Readers.IsNull()) {
          m_Readers = ReaderListType::New();
        }
        auto reader = ReaderType::New();
        reader->SetFileName(inFile);
        reader->UpdateOutputInformation();
        m_Readers->PushBack(reader);
        return reader;
    }


    AnglesImageType::Pointer            m_AnglesRaster;
    AnglesImageType::Pointer            m_AnglesMaskRaster;
    ImageResampler<AnglesImageType, AnglesImageType> m_AnglesResampler;
    AnglesMaskedOutputFilterType::Pointer m_AnglesMaskedOutputFunctor;
    ReaderListType::Pointer                      m_Readers;
    AnglesImageType::Pointer m_mskImg;
};
}
}

OTB_APPLICATION_EXPORT(otb::Wrapper::ApplyMaskToRaster)


