/**
 * Resolve an asset from Vite's public directory in both HTTP previews and the
 * packaged Electron renderer. Absolute web paths (`/brands/...`) otherwise
 * point to the root of the drive when the application is loaded with file://.
 */
export function publicAssetUrl(asset?: string | null) {
  if (!asset) return "";
  if (/^(?:data:|blob:|https?:)/i.test(asset)) return asset;

  const rendererDirectory = new URL(".", window.location.href);
  return new URL(asset.replace(/^\/+/, ""), rendererDirectory).toString();
}
