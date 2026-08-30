package tech.ula.library.model.repositories

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class R3LockedPayloadCatalogTest {

    // Shaped exactly as tools/render_runtime_catalog.py emits it.
    private val catalogJson = """
    {
      "apps": [
        {
          "abis": {
            "arm64": {
              "asset_list": ["busybox", "libdisableselinux.so", "nosudo"],
              "assets.tar.gz": {
                "filename": "arm64-assets.tar.gz",
                "release": "v7.7.9",
                "sha256": "1111111111111111111111111111111111111111111111111111111111111111",
                "size": 4096,
                "url": "https://example.invalid/v7.7.9/arm64-assets.tar.gz"
              },
              "rootfs.tar.gz": {
                "filename": "arm64-rootfs.tar.gz",
                "release": "v7.7.9",
                "sha256": "2222222222222222222222222222222222222222222222222222222222222222",
                "size": 209715200,
                "url": "https://example.invalid/v7.7.9/arm64-rootfs.tar.gz"
              }
            },
            "x86_64": {
              "asset_list": ["busybox"],
              "assets.tar.gz": {
                "filename": "x86_64-assets.tar.gz",
                "release": "v7.7.9",
                "sha256": "3333333333333333333333333333333333333333333333333333333333333333",
                "size": 4097,
                "url": "https://example.invalid/v7.7.9/x86_64-assets.tar.gz"
              },
              "rootfs.tar.gz": {
                "filename": "x86_64-rootfs.tar.gz",
                "release": "v7.7.9",
                "sha256": "4444444444444444444444444444444444444444444444444444444444444444",
                "size": 209715201,
                "url": "https://example.invalid/v7.7.9/x86_64-rootfs.tar.gz"
              }
            }
          },
          "id": "foxbox",
          "package_id": "tech.ula.foxbox_pro",
          "repository": "CypherpunkArmory/UserLAnd-Assets-Debian"
        },
        {
          "abis": {
            "arm64": {
              "asset_list": [],
              "assets.tar.gz": {
                "filename": "arm64-assets.tar.gz",
                "release": "v0.0.1",
                "sha256": "5555555555555555555555555555555555555555555555555555555555555555",
                "size": 8,
                "url": "https://example.invalid/v0.0.1/arm64-assets.tar.gz"
              },
              "rootfs.tar.gz": {
                "filename": "arm64-rootfs.tar.gz",
                "release": "v0.0.1",
                "sha256": "6666666666666666666666666666666666666666666666666666666666666666",
                "size": 9,
                "url": "https://example.invalid/v0.0.1/arm64-rootfs.tar.gz"
              }
            }
          },
          "id": "devstudio",
          "package_id": "tech.ula.devstudio",
          "repository": "Zfkirke0109/deVStudio"
        }
      ],
      "schema_version": 1
    }
    """.trimIndent()

    private val catalog = LockedPayloadCatalog.from(catalogJson)

    @Test
    fun resolvesAPayloadByPackageAndArchitecture() {
        val rootfs = catalog.payload(
            "tech.ula.foxbox_pro", "arm64", LockedPayloadCatalog.ROOTFS_PAYLOAD
        )

        assertEquals("arm64-rootfs.tar.gz", rootfs!!.filename)
        assertEquals("v7.7.9", rootfs.release)
        assertEquals("https://example.invalid/v7.7.9/arm64-rootfs.tar.gz", rootfs.url)
        assertEquals(209715200L, rootfs.size)
        assertEquals("22".repeat(32), rootfs.sha256)
    }

    @Test
    fun architecturesAreResolvedIndependently() {
        val arm = catalog.payload("tech.ula.foxbox_pro", "arm64", LockedPayloadCatalog.ASSETS_PAYLOAD)!!
        val intel = catalog.payload("tech.ula.foxbox_pro", "x86_64", LockedPayloadCatalog.ASSETS_PAYLOAD)!!

        assertEquals("11".repeat(32), arm.sha256)
        assertEquals("33".repeat(32), intel.sha256)
    }

    @Test
    fun packagesAreResolvedIndependently() {
        val foxbox = catalog.payload("tech.ula.foxbox_pro", "arm64", LockedPayloadCatalog.ROOTFS_PAYLOAD)!!
        val devstudio = catalog.payload("tech.ula.devstudio", "arm64", LockedPayloadCatalog.ROOTFS_PAYLOAD)!!

        assertEquals("v7.7.9", foxbox.release)
        assertEquals("v0.0.1", devstudio.release)
    }

    @Test
    fun anUnsupportedArchitectureResolvesToNothing() {
        // deVStudio ships no x86 ABI, so a lookup must not fall back to another one.
        assertNull(catalog.payload("tech.ula.devstudio", "x86", LockedPayloadCatalog.ROOTFS_PAYLOAD))
        assertFalse(catalog.supports("tech.ula.devstudio", "x86"))
        assertTrue(catalog.supports("tech.ula.devstudio", "arm64"))
    }

    @Test
    fun anUnknownPackageResolvesToNothing() {
        assertNull(catalog.payload("tech.ula.unknown", "arm64", LockedPayloadCatalog.ROOTFS_PAYLOAD))
        assertNull(catalog.app("tech.ula.unknown"))
        assertFalse(catalog.supports("tech.ula.unknown", "arm64"))
    }

    @Test
    fun assetListIsReadPerArchitecture() {
        assertEquals(
            listOf("busybox", "libdisableselinux.so", "nosudo"),
            catalog.assetList("tech.ula.foxbox_pro", "arm64")
        )
        assertEquals(listOf("busybox"), catalog.assetList("tech.ula.foxbox_pro", "x86_64"))
        assertEquals(emptyList<String>(), catalog.assetList("tech.ula.unknown", "arm64"))
    }

    @Test
    fun aPayloadMissingItsDigestIsNotSelectable() {
        val degraded = LockedPayloadCatalog.from(
            """
            {"schema_version":1,"apps":[{"id":"x","package_id":"tech.ula.x","repository":"r",
             "abis":{"arm64":{"asset_list":[],
               "rootfs.tar.gz":{"filename":"f","release":"v1","url":"https://example.invalid/f","size":1,"sha256":""}}}}]}
            """.trimIndent()
        )

        // Selecting by exact bytes is the whole point; an undigested entry is unusable.
        assertNull(degraded.payload("tech.ula.x", "arm64", LockedPayloadCatalog.ROOTFS_PAYLOAD))
    }

    @Test
    fun unknownFieldsAndFuturePayloadsAreTolerated() {
        val extended = LockedPayloadCatalog.from(
            """
            {"schema_version":2,"unexpected":[1,2],"apps":[{"id":"x","package_id":"tech.ula.x",
             "repository":"r","future":{"a":1},
             "abis":{"arm64":{"asset_list":["b"],
               "rootfs.tar.gz":{"filename":"f","release":"v1","url":"https://example.invalid/f",
                                "size":1,"sha256":"aa","future_field":7}}}}]}
            """.trimIndent()
        )

        assertEquals("aa", extended.payload("tech.ula.x", "arm64", LockedPayloadCatalog.ROOTFS_PAYLOAD)!!.sha256)
        assertEquals(listOf("b"), extended.assetList("tech.ula.x", "arm64"))
    }

    @Test
    fun everyLockedAppIsExposedForVerification() {
        assertEquals(2, catalog.apps.size)
        assertEquals(
            listOf("tech.ula.devstudio", "tech.ula.foxbox_pro"),
            catalog.apps.map { it.packageId }.sorted()
        )
    }
}
