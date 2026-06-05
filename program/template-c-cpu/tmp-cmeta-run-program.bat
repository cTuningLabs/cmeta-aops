@echo off

cd /d D:\!FGG_Repos\repos\ctuninglabs@cmeta-aops\program\template-c-cpu

set CMETA_TARGETS=cpu
set CMETA_TARGET_CPU=1
set CMETA_TARGET_CUDA=0
set CMETA_TARGET_OPU_LUMAI=0
set CMETA_TARGET_ROCM=0
set CMETA_TARGET_TPU=0
set CMETA_TARGET_XPU=0
set CommandPromptType=Native
set DevEnvDir=D:\Program Files\Microsoft Visual Studio\18\Community\Common7\IDE\
set EXTERNAL_INCLUDE=D:\Program Files\Microsoft Visual Studio\18\Community\VC\Tools\MSVC\14.50.35717\include;D:\Program Files\Microsoft Visual Studio\18\Community\VC\Tools\MSVC\14.50.35717\ATLMFC\include;D:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\VS\include;C:\Program Files (x86)\Windows Kits\10\include\10.0.26100.0\ucrt;C:\Program Files (x86)\Windows Kits\10\\include\10.0.26100.0\\um;C:\Program Files (x86)\Windows Kits\10\\include\10.0.26100.0\\shared;C:\Program Files (x86)\Windows Kits\10\\include\10.0.26100.0\\winrt;C:\Program Files (x86)\Windows Kits\10\\include\10.0.26100.0\\cppwinrt;C:\Program Files (x86)\Windows Kits\NETFXSDK\4.8\include\um
set ExtensionSdkDir=C:\Program Files (x86)\Microsoft SDKs\Windows Kits\10\ExtensionSDKs
set FSHARPINSTALLDIR=D:\Program Files\Microsoft Visual Studio\18\Community\Common7\IDE\CommonExtensions\Microsoft\FSharp\Tools
set Framework40Version=v4.0
set FrameworkDir=C:\Windows\Microsoft.NET\Framework64\
set FrameworkDir64=C:\Windows\Microsoft.NET\Framework64\
set FrameworkVersion=v4.0.30319
set FrameworkVersion64=v4.0.30319
set HTMLHelpDir=C:\Program Files (x86)\HTML Help Workshop
set INCLUDE=D:\Program Files\Microsoft Visual Studio\18\Community\VC\Tools\MSVC\14.50.35717\include;D:\Program Files\Microsoft Visual Studio\18\Community\VC\Tools\MSVC\14.50.35717\ATLMFC\include;D:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\VS\include;C:\Program Files (x86)\Windows Kits\10\include\10.0.26100.0\ucrt;C:\Program Files (x86)\Windows Kits\10\\include\10.0.26100.0\\um;C:\Program Files (x86)\Windows Kits\10\\include\10.0.26100.0\\shared;C:\Program Files (x86)\Windows Kits\10\\include\10.0.26100.0\\winrt;C:\Program Files (x86)\Windows Kits\10\\include\10.0.26100.0\\cppwinrt;C:\Program Files (x86)\Windows Kits\NETFXSDK\4.8\include\um
set LIB=D:\Program Files\Microsoft Visual Studio\18\Community\VC\Tools\MSVC\14.50.35717\ATLMFC\lib\x64;D:\Program Files\Microsoft Visual Studio\18\Community\VC\Tools\MSVC\14.50.35717\lib\x64;C:\Program Files (x86)\Windows Kits\NETFXSDK\4.8\lib\um\x64;C:\Program Files (x86)\Windows Kits\10\lib\10.0.26100.0\ucrt\x64;C:\Program Files (x86)\Windows Kits\10\\lib\10.0.26100.0\\um\x64
set LIBPATH=D:\Program Files\Microsoft Visual Studio\18\Community\VC\Tools\MSVC\14.50.35717\ATLMFC\lib\x64;D:\Program Files\Microsoft Visual Studio\18\Community\VC\Tools\MSVC\14.50.35717\lib\x64;D:\Program Files\Microsoft Visual Studio\18\Community\VC\Tools\MSVC\14.50.35717\lib\x86\store\references;C:\Program Files (x86)\Windows Kits\10\UnionMetadata\10.0.26100.0;C:\Program Files (x86)\Windows Kits\10\References\10.0.26100.0;C:\Windows\Microsoft.NET\Framework64\v4.0.30319
set NETFXSDKDir=C:\Program Files (x86)\Windows Kits\NETFXSDK\4.8\
set PATH=C:\Program Files (x86)\HTML Help Workshop;C:\Program Files (x86)\Microsoft SDKs\Windows\v10.0A\bin\NETFX 4.8 Tools\x64\;C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\\x64;C:\Program Files (x86)\Windows Kits\10\bin\\x64;C:\Windows\Microsoft.NET\Framework64\v4.0.30319;D:\Program Files\Microsoft Visual Studio\18\Community\Common7\IDE\;D:\Program Files\Microsoft Visual Studio\18\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin;D:\Program Files\Microsoft Visual Studio\18\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja;D:\Program Files\Microsoft Visual Studio\18\Community\Common7\IDE\CommonExtensions\Microsoft\FSharp\Tools;D:\Program Files\Microsoft Visual Studio\18\Community\Common7\IDE\CommonExtensions\Microsoft\TeamFoundation\Team Explorer;D:\Program Files\Microsoft Visual Studio\18\Community\Common7\IDE\CommonExtensions\Microsoft\TestWindow;D:\Program Files\Microsoft Visual Studio\18\Community\Common7\IDE\Extensions\Microsoft\CodeCoverage.Console;D:\Program Files\Microsoft Visual Studio\18\Community\Common7\IDE\VC\Linux\bin\ConnectionManagerExe;D:\Program Files\Microsoft Visual Studio\18\Community\Common7\IDE\VC\VCPackages;D:\Program Files\Microsoft Visual Studio\18\Community\Common7\Tools\;D:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\bin\Roslyn;D:\Program Files\Microsoft Visual Studio\18\Community\Team Tools\DiagnosticsHub\Collector;D:\Program Files\Microsoft Visual Studio\18\Community\VC\Tools\Llvm\x64\bin;D:\Program Files\Microsoft Visual Studio\18\Community\VC\Tools\MSVC\14.50.35717\bin\HostX64\x64;D:\Program Files\Microsoft Visual Studio\18\Community\VC\vcpkg;D:\Program Files\Microsoft Visual Studio\18\Community\\MSBuild\Current\Bin\amd64;C:\Program Files\GitHub CLI\;C:\!Progs\Python3.14.0\Scripts;C:\!Progs\Python3.14.0\;D:\!FGG\Progs\!fu;D:\!FGG\Progs\!Misc;C:\Program Files\Oculus\Support\oculus-runtime;C:\Program Files\WinRar;C:\!Progs\jdk-21.0.7+6-windows-build\bin;C:\!Progs\MiKTeX\miktex\bin\x64\;C:\Program Files\Graphviz\bin;C:\Program Files\dotnet\;C:\WINDOWS\system32;C:\WINDOWS;C:\WINDOWS\System32\Wbem;C:\WINDOWS\System32\WindowsPowerShell\v1.0\;C:\WINDOWS\System32\OpenSSH\;C:\Program Files (x86)\HP\HP OCR\DB_Lib\;C:\Program Files\HP\Common\HPDestPlgIn\;C:\Program Files (x86)\HP\Common\HPDestPlgIn\;C:\ProgramData\chocolatey\bin;C:\Program Files\RedHat\Podman\;C:\Program Files (x86)\Incredibuild;C:\Program Files\TortoiseGit\bin;C:\Program Files\Tailscale\;C:\Program Files\Microsoft SQL Server\170\Tools\Binn\;C:\Program Files\Microsoft SQL Server\Client SDK\ODBC\170\Tools\Binn\;C:\Program Files\Git\cmd;C:\Program Files\PowerToys\DSCModules\;C:\Program Files (x86)\AOMEI\AOMEI Backupper\8.3.0;C:\Program Files\NVIDIA Corporation\Nsight Compute 2026.1.1\;C:\Program Files\Docker\Docker\resources\bin;C:\Program Files\IrfanView;C:\Users\grigo\AppData\Local\Microsoft\WindowsApps;C:\Users\grigo\AppData\Local\Programs\Microsoft VS Code\bin;C:\Users\grigo\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin;C:\Users\grigo\AppData\Local\GitHubDesktop\bin;C:\Users\grigo\AppData\Local\Microsoft\WinGet\Links;C:\Program Files\HP\Common\HPDestPlgIn\;C:\Program Files (x86)\HP\Common\HPDestPlgIn\;C:\Users\grigo\AppData\Local\Programs\cursor\resources\app\bin;C:\Users\grigo\AppData\Local\Microsoft\WinGet\Packages\Google.PlatformTools_Microsoft.Winget.Source_8wekyb3d8bbwe\platform-tools;C:\Users\grigo\.dotnet\tools;C:\Users\grigo\AppData\Local\Microsoft\WindowsApps;C:\Users\grigo\AppData\Local\Programs\Swift\Toolchains\6.3.1+Asserts\usr\bin\;C:\Users\grigo\AppData\Local\Programs\Swift\Runtimes\6.3.1\usr\bin\
set Platform=x64
set UCRTVersion=10.0.26100.0
set UniversalCRTSdkDir=C:\Program Files (x86)\Windows Kits\10\
set VCIDEInstallDir=D:\Program Files\Microsoft Visual Studio\18\Community\Common7\IDE\VC\
set VCINSTALLDIR=D:\Program Files\Microsoft Visual Studio\18\Community\VC\
set VCPKG_ROOT=D:\Program Files\Microsoft Visual Studio\18\Community\VC\vcpkg
set VCToolsInstallDir=D:\Program Files\Microsoft Visual Studio\18\Community\VC\Tools\MSVC\14.50.35717\
set VCToolsRedistDir=D:\Program Files\Microsoft Visual Studio\18\Community\VC\Redist\MSVC\14.50.35710\
set VCToolsVersion=14.50.35717
set VS180COMNTOOLS=D:\Program Files\Microsoft Visual Studio\18\Community\Common7\Tools\
set VSCMD_ARG_HOST_ARCH=x64
set VSCMD_ARG_TGT_ARCH=x64
set VSCMD_ARG_app_plat=Desktop
set VSCMD_ARG_winsdk=10.0.26100.0
set VSCMD_VER=18.4.0
set VSINSTALLDIR=D:\Program Files\Microsoft Visual Studio\18\Community\
set VSSDK150INSTALL=D:\Program Files\Microsoft Visual Studio\18\Community\VSSDK
set VSSDKINSTALL=D:\Program Files\Microsoft Visual Studio\18\Community\VSSDK
set VisualStudioVersion=18.0
set WindowsLibPath=C:\Program Files (x86)\Windows Kits\10\UnionMetadata\10.0.26100.0;C:\Program Files (x86)\Windows Kits\10\References\10.0.26100.0
set WindowsSDKLibVersion=10.0.26100.0\
set WindowsSDKVersion=10.0.26100.0\
set WindowsSDK_ExecutablePath_x64=C:\Program Files (x86)\Microsoft SDKs\Windows\v10.0A\bin\NETFX 4.8 Tools\x64\
set WindowsSDK_ExecutablePath_x86=C:\Program Files (x86)\Microsoft SDKs\Windows\v10.0A\bin\NETFX 4.8 Tools\
set WindowsSdkBinPath=C:\Program Files (x86)\Windows Kits\10\bin\
set WindowsSdkDir=C:\Program Files (x86)\Windows Kits\10\
set WindowsSdkVerBinPath=C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\
set __DOTNET_ADD_64BIT=1
set __DOTNET_PREFERRED_BITNESS=64
set __VSCMD_PREINIT_PATH=C:\Program Files\GitHub CLI\;C:\!Progs\Python3.14.0\Scripts;C:\!Progs\Python3.14.0\;D:\!FGG\Progs\!fu;D:\!FGG\Progs\!Misc;C:\Program Files\Oculus\Support\oculus-runtime;C:\Program Files\WinRar;C:\!Progs\jdk-21.0.7+6-windows-build\bin;C:\!Progs\MiKTeX\miktex\bin\x64\;C:\Program Files\Graphviz\bin;C:\Program Files\dotnet\;C:\WINDOWS\system32;C:\WINDOWS;C:\WINDOWS\System32\Wbem;C:\WINDOWS\System32\WindowsPowerShell\v1.0\;C:\WINDOWS\System32\OpenSSH\;C:\Program Files (x86)\HP\HP OCR\DB_Lib\;C:\Program Files\HP\Common\HPDestPlgIn\;C:\Program Files (x86)\HP\Common\HPDestPlgIn\;C:\ProgramData\chocolatey\bin;C:\Program Files\RedHat\Podman\;C:\Program Files (x86)\Incredibuild;C:\Program Files\TortoiseGit\bin;C:\Program Files\Tailscale\;C:\Program Files\Microsoft SQL Server\170\Tools\Binn\;C:\Program Files\Microsoft SQL Server\Client SDK\ODBC\170\Tools\Binn\;C:\Program Files\Git\cmd;C:\Program Files\PowerToys\DSCModules\;C:\Program Files (x86)\AOMEI\AOMEI Backupper\8.3.0;C:\Program Files\NVIDIA Corporation\Nsight Compute 2026.1.1\;C:\Program Files\Docker\Docker\resources\bin;C:\Program Files\IrfanView;C:\Users\grigo\AppData\Local\Microsoft\WindowsApps;C:\Users\grigo\AppData\Local\Programs\Microsoft VS Code\bin;C:\Users\grigo\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin;C:\Users\grigo\AppData\Local\GitHubDesktop\bin;C:\Users\grigo\AppData\Local\Microsoft\WinGet\Links;C:\Program Files\HP\Common\HPDestPlgIn\;C:\Program Files (x86)\HP\Common\HPDestPlgIn\;C:\Users\grigo\AppData\Local\Programs\cursor\resources\app\bin;C:\Users\grigo\AppData\Local\Microsoft\WinGet\Packages\Google.PlatformTools_Microsoft.Winget.Source_8wekyb3d8bbwe\platform-tools;C:\Users\grigo\.dotnet\tools;C:\Users\grigo\AppData\Local\Microsoft\WindowsApps;C:\Users\grigo\AppData\Local\Programs\Swift\Toolchains\6.3.1+Asserts\usr\bin\;C:\Users\grigo\AppData\Local\Programs\Swift\Runtimes\6.3.1\usr\bin\
set is_x64_arch=true
set llvmArm64=D:\Program Files\Microsoft Visual Studio\18\Community\VC\Tools\Llvm\ARM64\bin
set llvmX64=D:\Program Files\Microsoft Visual Studio\18\Community\VC\Tools\Llvm\x64\bin
set llvmX86=D:\Program Files\Microsoft Visual Studio\18\Community\VC\Tools\Llvm\bin

program.exe  
