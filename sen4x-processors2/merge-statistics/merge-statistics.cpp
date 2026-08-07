#include <algorithm>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <limits>
#include <vector>

#include "entry.h"
#include "statistics-reader.h"

int main(int argc, char *argv[])
{
    if (argc % 3 != 0 || argc < 6) {
        std::cerr << "Usage: " << argv[0]
                  << " mean.csv dev.csv mean-1.csv dev-1.csv count-1.csv [...]\n";
        return 1;
    }

    std::vector<statistics_reader> statistics_readers;
    statistics_readers.reserve(argc / 3 - 1);

    std::ofstream fmean(argv[1]);
    std::ofstream fdev(argv[2]);

    for (int i = 3; i < argc; i += 3) {
        auto mean = argv[i];
        auto dev = argv[i + 1];
        auto count = argv[i + 2];
        statistics_readers.emplace_back(std::make_unique<std::ifstream>(mean),
                                        std::make_unique<std::ifstream>(dev),
                                        std::make_unique<std::ifstream>(count));
    }

    for (auto &statistics_reader : statistics_readers) {
        statistics_reader.next();
    }

    // https://stats.stackexchange.com/a/56000
    while (true) {
        statistics_readers.erase(
            std::remove_if(statistics_readers.begin(), statistics_readers.end(),
                           [](statistics_reader &r) { return r.is_finished(); }),
            statistics_readers.end());
        if (statistics_readers.empty()) {
            break;
        }

        auto key = std::numeric_limits<int64_t>::max();
        auto columns = 0;
        for (const auto &statistics_reader : statistics_readers) {
            if (key > statistics_reader.key()) {
                key = statistics_reader.key();
                columns = statistics_reader.columns();
            }
        }

        entry_real sum(columns);
        entry_count count(columns);
        for (auto &statistics_reader : statistics_readers) {
            if (key == statistics_reader.key()) {
                sum += statistics_reader.mean() * statistics_reader.count();
                count += statistics_reader.count();
            }
        }

        entry_real dev(columns);
        for (auto &statistics_reader : statistics_readers) {
            if (key == statistics_reader.key()) {
                for (size_t i = 0; i < columns; i++) {
                    auto m = statistics_reader.mean()[i];
                    auto d = statistics_reader.dev()[i];
                    auto c = statistics_reader.count()[i];
                    if (count[i] > 0) {
                        if (c > 1) {
                            auto mc = sum[i] / count[i];
                            dev[i] += (c - 1) * d * d + c * (m - mc) * (m - mc);
                        } else {
                            auto mc = sum[i] / count[i];
                            dev[i] += c * d * d + c * (m - mc) * (m - mc);
                        }
                    } else {
                        dev[i] = 0;
                    }
                }
                statistics_reader.next();
            }
        }

        for (size_t i = 0; i < columns; i++) {
            if (count[i] > 1) {
                dev[i] /= count[i] - 1;
            }
            dev[i] = std::sqrt(dev[i]);
        }

        fmean << key;
        for (size_t i = 0; i < columns; i++) {
            if (count[i] > 0) {
                fmean << ',' << sum[i] / count[i];
            } else {
                fmean << ',' << 0;
            }
        }
        fmean << '\n';

        fdev << key;
        for (size_t i = 0; i < columns; i++) {
            fdev << ',' << dev[i];
        }
        fdev << '\n';
    }
    return 0;
}
