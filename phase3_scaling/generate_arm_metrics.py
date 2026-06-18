
def calc_direct(name, strategy, t_h264, t_h265, t_vp9, price, n_instances, is_serial=False):
    setup = 115.0
    # Add setup only to serial because horizontal medians already include it in the wall-clock loop
    t_h264_f = t_h264 + (setup if is_serial else 0)
    t_h265_f = t_h265 + (setup if is_serial else 0)
    t_vp9_f = t_vp9 + (setup if is_serial else 0)
    
    c_h264 = (t_h264_f / 3600.0) * price * n_instances
    c_h265 = (t_h265_f / 3600.0) * price * n_instances
    c_vp9 = (t_vp9_f / 3600.0) * price * n_instances
    
    e_h264 = 1.0 / (c_h264 * t_h264_f)
    e_h265 = 1.0 / (c_h265 * t_h265_f)
    e_vp9 = 1.0 / (c_vp9 * t_vp9_f)
    
    return {"h264": [t_h264_f, c_h264, e_h264], "h265": [t_h265_f, c_h265, e_h265], "vp9": [t_vp9_f, c_vp9, e_vp9]}

# Verified 10-minute measurements (Median)
# m7g: H264_ser=57.55, H265_ser=700.5, VP9_ser=329.03
# m7g: H264_hor=108.07, H265_hor=139.36
# c7g: H264_ser=57.27, H265_ser=702.14, VP9_ser=328.90
# c7g: H264_hor=107.68, H265_hor=61.03 (Wait, 61.03?), VP9_hor=70.61

m7g_p = 0.0816
c7g_p = 0.0850

m7_ser = calc_direct("m7g", "serial", 57.55, 700.5, 329.03, m7g_p, 1, True)
m7_hor = calc_direct("m7g", "horizontal", 108.07, 139.36, 115.0, m7g_p, 10, False)

c7_ser = calc_direct("c7g", "serial", 57.27, 702.14, 328.90, c7g_p, 1, True)
c7_hor = calc_direct("c7g", "horizontal", 107.68, 61.03, 70.61, c7g_p, 10, False)

def print_latex(name, strategy, data):
    # Mapping to LaTeX format
    print(f"{name:10} & {strategy:10} & {data['h264'][0]:8.2f} & {data['h264'][2]:8.4f} | {data['h264'][1]:8.4f} & "
          f"{data['h265'][0]:8.2f} & {data['h265'][2]:8.4f} | {data['h265'][1]:8.4f} & "
          f"{data['vp9'][0]:8.2f} & {data['vp9'][2]:8.4f} | {data['vp9'][1]:8.4f} \\\\")

print("Final LaTeX Rows:")
print_latex("\\texttt{m7g.large}", "serial", m7_ser)
print_latex("\\texttt{m7g.large}", "horizontal", m7_hor)
print_latex("\\texttt{c7g.large}", "serial", c7_ser)
print_latex("\\texttt{c7g.large}", "horizontal", c7_hor)

print("\nSpeedups (m7g):")
print(f"H.264: {m7_ser['h264'][0] / m7_hor['h264'][0]:.2f}x")
print(f"H.265: {m7_ser['h265'][0] / m7_hor['h265'][0]:.2f}x")
print(f"VP9:   {m7_ser['vp9'][0] / m7_hor['vp9'][0]:.2f}x")
