/** The proxy strips /video before forwarding, but browser history must retain it. */
export function adminHistoryBase(
  pathname = globalThis.location?.pathname ?? '',
  buildBase = import.meta.env.BASE_URL,
) {
  const mount = new RegExp('^((?:/video)?/admin(?:-next)?)(?:/|$)').exec(pathname)
  return mount ? `${mount[1]}/` : buildBase
}

export function stableAdminHref(pathname = globalThis.location?.pathname ?? '') {
  return adminHistoryBase(pathname).replace(new RegExp('/admin-next/$'), '/admin/')
}
