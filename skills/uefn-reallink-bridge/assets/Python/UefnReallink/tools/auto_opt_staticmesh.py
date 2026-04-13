"""
扫描 /RPG2 下所有 StaticMesh:
  1. 按 LOD0 顶点数降序打印
  2. 批量设置 Nanite Fallback Target = Percent Triangles, 比例 10%
  注: UEFN 项目中 Nanite 通过 CVar 全局强制开启，nanite_settings.enabled 不代表实际状态
"""
import unreal

# ── 配置 ──────────────────────────────────────────────
FALLBACK_PERCENT = 0.1   # Nanite 回退网格体保留三角形比例 (10%)
# ──────────────────────────────────────────────────────


def run():
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    ar_filter = unreal.ARFilter(
        class_paths=[unreal.TopLevelAssetPath("/Script/Engine", "StaticMesh")],
        package_paths=["/RPG2"],
        recursive_paths=True,
    )
    asset_data_list = registry.get_assets(ar_filter)
    unreal.log(f"[OptSM] 共找到 {len(asset_data_list)} 个 StaticMesh 资产")

    # ── 第一步: 收集信息并按顶点数排序 ──
    mesh_info = []
    for ad in asset_data_list:
        pkg = str(ad.package_name)
        sm = unreal.EditorAssetLibrary.load_asset(pkg)
        if sm is None:
            continue
        verts = sm.get_num_vertices(0)
        ns = sm.get_editor_property("nanite_settings")
        mesh_info.append((pkg, sm, verts, ns.fallback_percent_triangles))

    mesh_info.sort(key=lambda x: x[2], reverse=True)

    unreal.log("=" * 70)
    unreal.log(f"[OptSM] StaticMesh 顶点数排行 (共 {len(mesh_info)} 个):")
    unreal.log("=" * 70)
    for i, (path, _, verts, fb) in enumerate(mesh_info, 1):
        unreal.log(f"  {i:>4}.  {verts:>8} verts  Fallback:{fb*100:.1f}%  |  {path}")
    unreal.log("=" * 70)

    # ── 第二步: 批量设置 Nanite Fallback (UEFN 全局强制 Nanite, 不按 enabled 过滤) ──
    targets = [(p, sm) for p, sm, v, fb in mesh_info if abs(fb - FALLBACK_PERCENT) > 0.001]
    unreal.log(f"[OptSM] 需要修改 Fallback 的有 {len(targets)} 个 (目标: {FALLBACK_PERCENT*100:.0f}%)")

    success_count = 0
    for pkg, sm in targets:
        sm.modify()
        ns = sm.get_editor_property("nanite_settings")
        ns.fallback_target = unreal.NaniteFallbackTarget.PERCENT_TRIANGLES
        ns.fallback_percent_triangles = FALLBACK_PERCENT
        sm.set_editor_property("nanite_settings", ns)
        unreal.EditorAssetLibrary.save_asset(pkg, only_if_is_dirty=False)
        success_count += 1

    unreal.log("=" * 70)
    unreal.log(f"[OptSM] 完成: {success_count}/{len(targets)} 个已设置 Fallback 为 {FALLBACK_PERCENT*100:.0f}%")
    unreal.log("=" * 70)


if __name__ == "__main__":
    run()
