# 获取socket中的真实IP
def get_real_ip(header_maps):
    """

    :param header_maps: dict
    :return:
    """
    maps = header_maps  # type: dict
    xip = maps.get("x-real-ip")  # type: str
    x_for = maps.get("x-forwarded-for")  # type: str

    if x_for and x_for != "unknown":
        # 多次反向代理后会有多个IP值，第一个IP才是真正的IP
        ip, other = x_for.split(",", 1)
        return ip
    x_for = xip
    if x_for and x_for != "unknown":
        return x_for
    if x_for or x_for == "unknown":
        x_for = maps.get("proxy-client-ip")
    if x_for or x_for == "unknown":
        x_for = maps.get("wl-proxy-client-ip")
    if x_for or x_for == "unknown":
        x_for = maps.get("http_client_ip")
    if x_for or x_for == "unknown":
        x_for = maps.get("http_x_forward_for")
    return x_for
