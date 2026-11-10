/*
MIT License
Copyright (c) Microsoft Corporation.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

ParseArgument body from microsoft/WSL src/windows/common/helpers.cpp,
viewed 2026-10-31. Only namespace/SAL annotations removed for a portable harness.
Default HandleQuotes=false from helpers.hpp, as used by WslClient.cpp WslMain.
https://github.com/microsoft/WSL/blob/master/src/windows/common/helpers.cpp
https://github.com/microsoft/WSL/blob/master/src/windows/common/helpers.hpp
https://github.com/microsoft/WSL/blob/master/src/windows/common/WslClient.cpp
The harness tests this parser on Linux; it is not the full Windows WSL runtime.
*/
#include <codecvt>
#include <iostream>
#include <locale>
#include <string>
#include <string_view>

std::wstring_view ParseArgument(std::wstring_view CommandLine, bool HandleQuotes = false)
{
    std::wstring_view Argument = CommandLine;
    const size_t Index = Argument.find_first_of(L" \t");
    if (Index != std::wstring_view::npos)
    {
        Argument = Argument.substr(0, Index);
    }
    if (HandleQuotes && CommandLine.find_first_of(L"\"") == 0)
    {
        const auto QuoteIndex = CommandLine.find_first_of(L"\"", 1);
        if (QuoteIndex != std::wstring_view::npos)
        {
            Argument = CommandLine.substr(0, QuoteIndex + 1);
        }
    }

    return Argument;
}

int main(int argc, char** argv)
{
    if(argc != 3) return 2;
    std::wstring_convert<std::codecvt_utf8<wchar_t>> convert;
    const auto commandLine = convert.from_bytes(argv[1]);
    const auto argument = ParseArgument(commandLine, std::string(argv[2]) == "1");
    std::cout << convert.to_bytes(argument.data(), argument.data() + argument.size());
}
