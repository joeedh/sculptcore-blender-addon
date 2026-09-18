# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

cmake_minimum_required(VERSION 3.21)
project(GitImportProbe NONE)
set(CMAKE_MAP_IMPORTED_CONFIG_RELEASE Release RelWithDebInfo MinSizeRel Debug)
if(WITH_GENERIC_LOCATION_FALLBACK)
  list(APPEND CMAKE_MAP_IMPORTED_CONFIG_RELEASE "")
endif()
find_package(Git REQUIRED)
file(GENERATE OUTPUT "git-path.txt" CONTENT "$<TARGET_FILE:Git::Git>\n")
