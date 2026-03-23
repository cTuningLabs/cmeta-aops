#include <iostream>
#include <cstdlib>

void printEnv(const char* name)
{
    const char* value = std::getenv(name);

    std::cout << name << " = ";
    if (value)
        std::cout << "\"" << value << "\"" ;
    else
        std::cout << "(not set)";

    std::cout << std::endl;
}

int main()
{
    printEnv("WindowsSdkDir");
    printEnv("WindowsSDKVersion");
    printEnv("WindowsSDKLibVersion");
    printEnv("UCRTVersion");
    printEnv("VCToolsVersion");

    return 0;
}
