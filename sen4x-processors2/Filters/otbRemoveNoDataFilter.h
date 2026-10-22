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

#ifndef otbRemoveNoDataFilter_h
#define otbRemoveNoDataFilter_h

#include "itkChangeInformationImageFilter.h"
#include "otbImageMetadata.h"

namespace otb
{

template <class TImage>
class RemoveNoDataFilter : public itk::ChangeInformationImageFilter<TImage>
{
public:
    using Self = RemoveNoDataFilter;
    using Superclass = itk::ChangeInformationImageFilter<TImage>;
    using Pointer = itk::SmartPointer<Self>;
    using ConstPointer = itk::SmartPointer<const Self>;

    itkNewMacro(Self);
    itkTypeMacro(RemoveNoDataFilter, ChangeInformationImageFilter);

protected:
    RemoveNoDataFilter() = default;
    ~RemoveNoDataFilter() override = default;

    void GenerateOutputInformation() override
    {
        Superclass::GenerateOutputInformation();

        auto &metadata = this->GetOutput()->GetImageMetadata();
        metadata.Remove(MDNum::NoData);
        for (auto &band : metadata.Bands) {
            band.Remove(MDNum::NoData);
        }
    }

private:
    RemoveNoDataFilter(const Self &) = delete;
    void operator=(const Self &) = delete;
};

}

#endif
