#!/bin/bash
# Builds every native input of the Madeira app that is not in its repository
# (docs/BUILDING.md upstream), on a macOS machine with Xcode 26:
#
#   madeira/ci/build-native.sh MADEIRA_DIR [STAGE...]
#
# Stages, in order: tools llvm gnutls ffmpeg wine-config wine-headers freetype wine-unix dxmt fex
# rppairing extras
# (all of them without arguments). A stage whose outputs exist is skipped, so a
# CI cache of toolchains/ and FEX/build-ios turns most of it into a no-op.
set -euo pipefail

M="$(cd "$1" && pwd)"; shift
STAGES=("$@")
[ ${#STAGES[@]} -gt 0 ] || STAGES=(tools llvm gnutls ffmpeg wine-config wine-headers freetype wine-unix dxmt fex rppairing extras)
T="$M/toolchains"
mkdir -p "$T"
JOBS="$(sysctl -n hw.ncpu)"

LLVM_VERSION=15.0.7
LLVM_MINGW=llvm-mingw-20260421-ucrt-macos-universal
LLVM_MINGW_SHA256=bd85a3975723815cef28dbbd2ca2cb0c926f6b348a12a0453f39f7af273cb3f7
# The LLVM libraries DXMT's airconv links (dxmt/src/airconv/meson.build).
LLVM_LIBS=(LLVMPasses LLVMTarget LLVMObjCARCOpts LLVMCoroutines LLVMipo LLVMInstrumentation
    LLVMVectorize LLVMLinker LLVMIRReader LLVMAsmParser LLVMFrontendOpenMP LLVMScalarOpts
    LLVMInstCombine LLVMAggressiveInstCombine LLVMTransformUtils LLVMBitWriter LLVMAnalysis
    LLVMProfileData LLVMSymbolize LLVMDebugInfoPDB LLVMDebugInfoMSF LLVMDebugInfoDWARF LLVMObject
    LLVMTextAPI LLVMMCParser LLVMMC LLVMDebugInfoCodeView LLVMBitReader LLVMCore LLVMRemarks
    LLVMBitstreamReader LLVMBinaryFormat LLVMSupport LLVMDemangle)

say() { printf '\n==== %s ====\n' "$*"; }

stage_tools() {
    say "tools"
    brew list bison >/dev/null 2>&1 || brew install bison
    for t in meson ninja ccache pkg-config; do command -v "$t" >/dev/null || brew install "$t"; done
    command -v cargo >/dev/null || { curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal; }
    # shellcheck disable=SC1091
    [ -f "$HOME/.cargo/env" ] && . "$HOME/.cargo/env"
    rustup target add aarch64-apple-ios
    # DXMT compiles its .metal shaders with the Metal toolchain, a separate download since Xcode 26.
    xcrun -sdk macosx metal --version >/dev/null 2>&1 || xcodebuild -downloadComponent MetalToolchain
}

stage_llvm() {
    local src="$T/llvm-project" build="$T/llvm-ios-build" host="$T/llvm-host-build"
    if [ -f "$build/lib/libLLVMSupport.a" ] && [ -f "$build/lib/libLLVMPasses.a" ]; then say "llvm (cached)"; return; fi
    say "llvm $LLVM_VERSION for iOS"
    if [ ! -d "$src/llvm" ]; then
        mkdir -p "$src"
        curl -sSfL "https://github.com/llvm/llvm-project/releases/download/llvmorg-$LLVM_VERSION/llvm-project-$LLVM_VERSION.src.tar.xz" \
            | tar -xJ -C "$src" --strip-components=1 "llvm-project-$LLVM_VERSION.src/llvm" "llvm-project-$LLVM_VERSION.src/cmake" "llvm-project-$LLVM_VERSION.src/third-party"
        # Apple's linker takes -dead_strip, not --gc-sections (build/dxmt-ios/README.md upstream).
        sed -i '' 's/MATCHES "Darwin")/MATCHES "Darwin|iOS")/' "$src/llvm/cmake/modules/AddLLVM.cmake"
    fi
    cmake -S "$src/llvm" -B "$host" -G Ninja -DCMAKE_BUILD_TYPE=Release -DLLVM_TARGETS_TO_BUILD= \
        -DLLVM_INCLUDE_TESTS=OFF -DLLVM_INCLUDE_BENCHMARKS=OFF -DLLVM_ENABLE_ZLIB=OFF -DLLVM_ENABLE_ZSTD=OFF
    ninja -C "$host" llvm-tblgen
    cmake -S "$src/llvm" -B "$build" -G Ninja -DCMAKE_SYSTEM_NAME=iOS -DCMAKE_OSX_ARCHITECTURES=arm64 \
        -DCMAKE_OSX_SYSROOT=iphoneos -DCMAKE_OSX_DEPLOYMENT_TARGET=17.0 -DCMAKE_BUILD_TYPE=Release \
        -DLLVM_HOST_TRIPLE=arm64-apple-ios17.0 -DLLVM_DEFAULT_TARGET_TRIPLE=arm64-apple-ios17.0 \
        -DLLVM_TARGET_ARCH=host -DLLVM_TARGETS_TO_BUILD= -DLLVM_ENABLE_PROJECTS= -DLLVM_BUILD_TOOLS=OFF \
        -DLLVM_BUILD_UTILS=OFF -DLLVM_INCLUDE_TOOLS=OFF -DLLVM_INCLUDE_UTILS=OFF -DLLVM_INCLUDE_TESTS=OFF \
        -DLLVM_INCLUDE_BENCHMARKS=OFF -DLLVM_INCLUDE_EXAMPLES=OFF -DLLVM_ENABLE_ZLIB=OFF -DLLVM_ENABLE_ZSTD=OFF \
        -DLLVM_ENABLE_TERMINFO=OFF -DLLVM_ENABLE_LIBXML2=OFF -DLLVM_TABLEGEN="$host/bin/llvm-tblgen"
    ninja -C "$build" -j "$JOBS" "${LLVM_LIBS[@]}"
}

stage_gnutls() {
    if [ -f "$T/gnutls-ios/include/gnutls/gnutls.h" ]; then say "gnutls (cached)"; return; fi
    say "gnutls"
    bash "$M/build/gnutls-ios/build.sh"
}

stage_ffmpeg() {
    if [ -f "$T/ffmpeg-ios/include/libavcodec/avcodec.h" ] && [ -f "$T/ffmpeg-ios/lib/libavcodec.a" ]; then
        say "ffmpeg (cached)"
    else
        say "ffmpeg"
        bash "$M/build/ffmpeg/build.sh"
    fi
    # The app links the archives from app/Madeira (ignored there).
    for l in avformat avcodec swresample avutil; do
        [ -f "$M/app/Madeira/lib$l.a" ] || cp "$T/ffmpeg-ios/lib/lib$l.a" "$M/app/Madeira/"
    done
}

stage_wine_config() {
    # The unix-side build scripts read config.h from a configured macOS tree
    # (wine/build-macos). Only configure is needed, not a build.
    if [ -f "$M/wine/build-macos/include/config.h" ]; then say "wine configure (done)"; return; fi
    say "wine configure"
    if [ ! -d "$T/$LLVM_MINGW" ]; then
        curl -sSfL -o "$T/$LLVM_MINGW.tar.xz" "https://github.com/mstorsjo/llvm-mingw/releases/download/20260421/$LLVM_MINGW.tar.xz"
        echo "$LLVM_MINGW_SHA256  $T/$LLVM_MINGW.tar.xz" | shasum -a 256 -c -
        tar -xJf "$T/$LLVM_MINGW.tar.xz" -C "$T" && rm "$T/$LLVM_MINGW.tar.xz"
    fi
    mkdir -p "$M/wine/build-macos"
    (cd "$M/wine/build-macos" && PATH="$T/$LLVM_MINGW/bin:$(brew --prefix bison)/bin:$PATH" \
        ../configure --enable-archs=aarch64 --without-x --without-vulkan --without-freetype --disable-tests)
}

stage_wine_headers() {
    # Some unix sides include widl-generated headers (dwrite_3.h for dwrite,
    # mfobjects.h and mftransform.h for winegstreamer), which only a build
    # creates. Generate every include/*.idl header in build-macos.
    local b="$M/wine/build-macos"
    if [ -f "$b/include/dwrite_3.h" ] && [ -f "$b/include/mftransform.h" ]; then say "wine headers (done)"; return; fi
    say "wine generated headers"
    local targets=() f
    for f in "$M"/wine/include/*.idl; do targets+=("include/$(basename "${f%.idl}").h"); done
    PATH="$(brew --prefix bison)/bin:$PATH" make -C "$b" -k -j "$JOBS" "${targets[@]}" >"$T/wine-headers.log" 2>&1 || true
    for f in dwrite_3.h mfobjects.h mftransform.h; do
        [ -f "$b/include/$f" ] || { tail -40 "$T/wine-headers.log"; echo "error: wine/build-macos/include/$f was not generated"; exit 1; }
    done
}

stage_freetype() {
    # win32u and dwrite link FreeType statically (build/freetype-ios).
    local src="$M/research/freetype"
    if [ -f "$M/build/freetype-ios/build/libfreetype.a" ]; then say "freetype (done)"; return; fi
    say "freetype"
    [ -d "$src" ] || git clone -q --depth 1 --branch VER-2-13-3 https://github.com/freetype/freetype.git "$src"
    bash "$M/build/freetype-ios/build.sh"
}

# The unix-side scripts keep each file's compiler errors in obj/NAME.err.
show_errors() {
    local e
    for e in "$M"/build/"$1"/obj/*.err "$M"/build/"$1"/obj/err-*.txt; do
        [ -f "$e" ] || continue
        [ -s "$e" ] || continue
        grep -q "error:" "$e" || continue
        echo "---- ${e#"$M"/} ----"
        grep -m 20 -B 2 -A 3 "error:" "$e" || true
    done
}

stage_wine_unix() {
    say "wine unix side (ntdll, wineserver, win32u)"
    # wineserver's script renames symbols with llvm-objcopy, which llvm-mingw has.
    export PATH="$PATH:$T/$LLVM_MINGW/bin"
    local d failed=0
    for d in ntdll-unix wineserver win32u-unix; do
        bash "$M/build/$d/build.sh" || { show_errors "$d"; failed=1; }
    done
    [ "$failed" = 0 ] || exit 1
    for l in ntdll_unix wineserver win32u_unix; do
        [ -f "$M/app/Madeira/lib$l.a" ] || { echo "error: app/Madeira/lib$l.a was not produced"; exit 1; }
    done
}

stage_dxmt() {
    say "dxmt unix side"
    bash "$M/build/dxmt-ios/build.sh"
    # The app links libdxmt_combined.a: DXMT's objects plus the LLVM archives
    # airconv needs, merged into one archive.
    local libs=() l
    for l in "${LLVM_LIBS[@]}"; do libs+=("$T/llvm-ios-build/lib/lib$l.a"); done
    libtool -static -no_warning_for_no_symbols -o "$M/app/Madeira/libdxmt_combined.a" \
        "$M/build/dxmt-ios/libdxmt_unix.a" "${libs[@]}"
}

stage_fex() {
    say "FEX for iOS"
    bash "$M/build/fex-ios/build.sh"
}

stage_rppairing() {
    if [ -f "$M/app/Madeira/libmadeira_rppairing.a" ]; then say "rppairing (done)"; return; fi
    say "rppairing"
    # shellcheck disable=SC1091
    [ -f "$HOME/.cargo/env" ] && . "$HOME/.cargo/env"
    bash "$M/build/rppairing-ios/build.sh"
}

stage_extras() {
    say "extras"
    # Microsoft's VC++ runtime is not redistributable here; the project
    # references the folder, so it exists, empty (docs/BUILDING.md upstream).
    mkdir -p "$M/app/Madeira/x86_64-vcruntime"
}

for s in "${STAGES[@]}"; do
    "stage_${s//-/_}"
done
