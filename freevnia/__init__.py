"""FreEvnia - unofficial open-source control for Philips Evnia monitors (DDC/CI over USB)."""
__version__ = "0.1.3"


def _use_bundled_libusb():
    """AppImage / pip installs without a system libusb: fall back to the one shipped by libusb-package."""
    import functools
    import usb.backend.libusb1 as libusb1
    import usb.core
    if libusb1.get_backend() is not None:
        return
    try:
        import libusb_package
    except ImportError:
        return
    backend = libusb1.get_backend(find_library=libusb_package.find_library)
    if backend is not None:
        usb.core.find = functools.partial(usb.core.find, backend=backend)


_use_bundled_libusb()
