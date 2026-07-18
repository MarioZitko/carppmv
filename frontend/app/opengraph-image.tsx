import { ImageResponse } from "next/og";

export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpengraphImage() {
	return new ImageResponse(
		(
			<div
				style={{
					width: "100%",
					height: "100%",
					display: "flex",
					flexDirection: "column",
					alignItems: "center",
					justifyContent: "center",
					background: "linear-gradient(135deg, #4f46e5 0%, #4338ca 100%)",
					color: "#ffffff",
					fontFamily: "sans-serif",
				}}
			>
				<div
					style={{
						display: "flex",
						alignItems: "center",
						gap: 24,
						fontSize: 72,
						fontWeight: 700,
					}}
				>
					carPPMV
				</div>
				<div style={{ display: "flex", fontSize: 36, marginTop: 20, opacity: 0.92 }}>
					Izračun PPMV-a za uvoz automobila
				</div>
				<div style={{ display: "flex", fontSize: 26, marginTop: 28, opacity: 0.75 }}>
					kalkulatoruvoza.com
				</div>
			</div>
		),
		{ ...size },
	);
}
