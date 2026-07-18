import type { MetadataRoute } from "next";

const SITE_URL = "https://kalkulatoruvoza.com";

export default function sitemap(): MetadataRoute.Sitemap {
	return [
		{
			url: SITE_URL,
			lastModified: new Date(),
			changeFrequency: "weekly",
			priority: 1,
		},
		{
			url: `${SITE_URL}/profitability`,
			lastModified: new Date(),
			changeFrequency: "weekly",
			priority: 0.6,
		},
	];
}
