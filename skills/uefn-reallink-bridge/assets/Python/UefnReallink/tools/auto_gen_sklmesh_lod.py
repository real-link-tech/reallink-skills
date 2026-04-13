"""
扫描 /RPG2 下 LOD 数量为 1 的 SkeletalMesh，自动 regenerate 到 4 级 LOD 并保存。
"""

import unreal

TARGET_LOD_COUNT = 4


def scan_and_fix_lod():
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    ar_filter = unreal.ARFilter(
        class_paths=[unreal.TopLevelAssetPath("/Script/Engine", "SkeletalMesh")],
        package_paths=["/RPG2"],
        recursive_paths=True,
    )
    asset_data_list = registry.get_assets(ar_filter)
    unreal.log(f"[ScanSKM] 共找到 {len(asset_data_list)} 个 SkeletalMesh 资产")

    single_lod = []
    for ad in asset_data_list:
        skm = unreal.EditorAssetLibrary.load_asset(str(ad.package_name))
        if skm is None:
            continue
        if unreal.EditorSkeletalMeshLibrary.get_lod_count(skm) == 1:
            single_lod.append((str(ad.package_name), skm))

    unreal.log(f"[ScanSKM] 其中 LOD=1 的有 {len(single_lod)} 个，开始 regenerate 到 {TARGET_LOD_COUNT} 级...")

    success_count = 0
    fail_list = []
    for pkg_name, skm in single_lod:
        ok = unreal.EditorSkeletalMeshLibrary.regenerate_lod(
            skm,
            new_lod_count=TARGET_LOD_COUNT,
            regenerate_even_if_imported=True,
            generate_base_lod=False,
        )
        if ok:
            unreal.EditorAssetLibrary.save_asset(pkg_name, only_if_is_dirty=False)
            new_count = unreal.EditorSkeletalMeshLibrary.get_lod_count(skm)
            unreal.log(f"  [OK] {pkg_name}  LOD: 1 -> {new_count}")
            success_count += 1
        else:
            unreal.log_warning(f"  [FAIL] {pkg_name}")
            fail_list.append(pkg_name)

    unreal.log("=" * 60)
    unreal.log(f"[ScanSKM] 完成: {success_count}/{len(single_lod)} 成功, {len(fail_list)} 失败")
    if fail_list:
        for f in fail_list:
            unreal.log_warning(f"  失败: {f}")
    unreal.log("=" * 60)


if __name__ == "__main__":
    scan_and_fix_lod()
