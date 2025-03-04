# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
# pylint: disable=invalid-name
"""Tools/compilers/linkers for Hexagon"""

import os
import pathlib
from typing import Union

import tvm
import tvm.contrib.cc as cc
from ..._ffi.registry import register_func


# Linking Hexagon shared libraries.
#
#   link_shared(name-of-shared-library, list-of-objects, kw-args)
#
# To use a custom linker, define a function that returns the path to the
# linker, and pass it to 'register_linker':
#
#   def custom_linker_path():
#       return '/path/to/hexagon/linker'
#
#   register_linker(custom_linker_path)
#
# Subsequent calls to 'link_shared' will use the newly registered linker.

HEXAGON_TOOLCHAIN = os.environ.get("HEXAGON_TOOLCHAIN", default="")  # pylint: disable=invalid-name
HEXAGON_SDK_PATH = os.environ.get("HEXAGON_SDK_PATH", default="")  # pylint: disable=invalid-name
HEXAGON_LINK_MAIN = (
    pathlib.Path(HEXAGON_TOOLCHAIN) / "bin" / "hexagon-link"
)  # pylint: disable=invalid-name
HEXAGON_CLANG_PLUS = (
    pathlib.Path(HEXAGON_TOOLCHAIN) / "bin" / "hexagon-clang++"
)  # pylint: disable=invalid-name
HEXAGON_SDK_INCLUDE_DIRS = [  # pylint: disable=invalid-name
    pathlib.Path(HEXAGON_SDK_PATH) / "incs",
    pathlib.Path(HEXAGON_SDK_PATH) / "incs" / "stddef",
]


def register_linker(f):
    """Register a function that will return the path to the Hexagon linker."""
    return register_func("tvm.contrib.hexagon.hexagon_link", f, True)


@register_func("tvm.contrib.hexagon.hexagon_link")
def hexagon_link() -> str:
    """Return path to the Hexagon linker."""
    return str(HEXAGON_LINK_MAIN)


def hexagon_clang_plus() -> str:
    """Return path to the Hexagon clang++."""
    return str(HEXAGON_CLANG_PLUS)


@register_func("tvm.contrib.hexagon.link_shared")
def link_shared(so_name, objs, extra_args=None):
    """Link shared library on Hexagon using the registered Hexagon linker.

    Parameters
    ----------
    so_name : str
        Name of the shared library file.
    objs : list[str,StringImm]
    extra_args : dict (str->str) or Map<String,String>
        Additional arguments:
            'hex_arch' - Hexagon architecture, e.g. v66
            'verbose'  - Print additional information if the key is present

    Returns
    -------
    ret_val : int
        This function returns 0 at the moment.
    """
    # The list of object files can be passed as built-in Python strings,
    # or as tvm.tir.StringImm's.
    def to_str(s):
        if isinstance(s, tvm.tir.StringImm):
            return s.value
        assert isinstance(s, str), 'argument "' + str(s) + '" should be a string or StrImm'
        return s

    objs = [to_str(s) for s in objs]

    if not extra_args:
        extra_args = {}
    hex_arch = extra_args.get("hex_arch") or "v66"
    linker = tvm.get_global_func("tvm.contrib.hexagon.hexagon_link")()
    if extra_args.get("verbose"):
        print("tvm.contrib.hexagon.link_shared:")
        print("  Using linker:", linker)
        print("  Library name:", so_name)
        print("  Object files:", objs)
        print("  Architecture:", hex_arch)
    if not os.access(linker, os.X_OK):
        message = 'The linker "' + linker + '" does not exist or is not executable.'
        if not os.environ.get("HEXAGON_TOOLCHAIN"):
            message += (
                " The environment variable HEXAGON_TOOLCHAIN is unset. Please export "
                + "HEXAGON_TOOLCHAIN in your environment, so that ${HEXAGON_TOOLCHAIN}/bin/"
                + "hexagon-link exists."
            )
        else:
            message += (
                " Please verify the value of the HEXAGON_LINKER environment variable "
                + '(currently set to "'
                + HEXAGON_TOOLCHAIN
                + '").'
            )
        raise Exception(message)

    libpath = os.path.join(HEXAGON_TOOLCHAIN, "target", "hexagon", "lib", hex_arch, "G0")
    cc.create_shared(
        so_name,
        objs,
        # pylint: disable=bad-whitespace
        options=[
            "-Bdynamic",
            "-shared",
            "-export-dynamic",
            os.path.join(libpath, "pic", "libgcc.so"),
        ],
        cc=linker,
    )
    return 0


def create_aot_shared(so_name: Union[str, pathlib.Path], files, hexagon_arch: str, options=None):
    """Export Hexagon AOT module."""
    options = options or []
    if not os.access(str(HEXAGON_CLANG_PLUS), os.X_OK):
        raise Exception(
            'The Clang++ "' + str(HEXAGON_CLANG_PLUS) + '" does not exist or is not executable.'
        )
    if not HEXAGON_TOOLCHAIN:
        raise Exception(
            " The environment variable HEXAGON_TOOLCHAIN is unset. Please export "
            + "HEXAGON_TOOLCHAIN in your environment."
        )
    if not HEXAGON_SDK_PATH:
        raise Exception(
            " The environment variable HEXAGON_SDK_PATH is unset. Please export "
            + "HEXAGON_SDK_PATH in your environment."
        )

    tvm_dir = pathlib.Path(os.path.dirname(os.path.realpath(__file__))) / ".." / ".." / ".." / ".."
    compute_arch = f"compute{hexagon_arch}"
    compile_options = [
        f"-O3",
        f"-I{tvm_dir / 'include'}",
        f"-I{tvm_dir / '3rdparty' / 'dlpack' / 'include'}",
        f"-I{tvm_dir / '3rdparty' / 'dmlc-core' / 'include'}",
        f"-I{pathlib.Path(HEXAGON_SDK_PATH) / 'rtos' / 'qurt' / compute_arch / 'include'/ 'posix'}",
        f"-I{pathlib.Path(HEXAGON_SDK_PATH) / 'rtos' / 'qurt' / compute_arch / 'include' / 'qurt'}",
        f"-DDMLC_USE_LOGGING_LIBRARY=<tvm/runtime/logging.h>",
        f"-D_MACH_I32=int",
    ]

    # For debugging
    for path in HEXAGON_SDK_INCLUDE_DIRS:
        compile_options.append(f"-I{str(path)}")

    cross_compile = cc.cross_compiler(compile_func=hexagon_clang_plus())
    cross_compile.output_format = "o"
    c_files = [str(file) for file in files]
    cross_compile(str(so_name), c_files, options=compile_options + options)
