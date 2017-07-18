find_package(TIFF REQUIRED)
CHECK_LIB_ONLY(JPEG jpeg)

message_var(TIFF_LIBRARIES)

include(FindPackageHandleStandardArgs)
find_package_handle_standard_args(TIFF
		REQUIRED_VARS TIFF_LIBRARIES
		)

if(TIFF_FOUND AND NOT TARGET TIFF)
	add_library(TIFF INTERFACE)
	add_library(TIFF::TIFF ALIAS TIFF)
	set_target_properties(TIFF PROPERTIES
			INTERFACE_LINK_LIBRARIES      "${TIFF_LIBRARIES};${JPEG_LIBRARY}"
			INTERFACE_COMPILE_DEFINITIONS USE_TIFF
			)
endif()
