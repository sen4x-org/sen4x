#!/bin/sh
function format_folder() {
    folder=$1
    echo "Formatting files in ${folder}"
    find $folder -name "*.h" -exec clang-format -i {} +
    find $folder -name "*.hpp" -exec clang-format -i {} +
    find $folder -name "*.cpp" -exec clang-format -i {} +
}

format_folder "sen4x-common"
format_folder "sen4x-http-listener"
format_folder "sen4x-orchestrator"
format_folder "sen4x-persistence"
format_folder "tests"
