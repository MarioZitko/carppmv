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
		{
			url: `${SITE_URL}/o-kalkulatoru`,
			lastModified: new Date(),
			changeFrequency: "monthly",
			priority: 0.6,
		},
		{
			url: `${SITE_URL}/kako-se-izracunava-ppmv`,
			lastModified: new Date(),
			changeFrequency: "monthly",
			priority: 0.8,
		},
		{
			url: `${SITE_URL}/nedc-vs-wltp`,
			lastModified: new Date(),
			changeFrequency: "monthly",
			priority: 0.7,
		},
		{
			url: `${SITE_URL}/vodic-uvoz-njemacka`,
			lastModified: new Date(),
			changeFrequency: "monthly",
			priority: 0.7,
		},
		{
			url: `${SITE_URL}/cesta-pitanja`,
			lastModified: new Date(),
			changeFrequency: "monthly",
			priority: 0.7,
		},
		{
			url: `${SITE_URL}/privatnost`,
			lastModified: new Date(),
			changeFrequency: "yearly",
			priority: 0.3,
		},
		{
			url: `${SITE_URL}/kolacici`,
			lastModified: new Date(),
			changeFrequency: "yearly",
			priority: 0.3,
		},
	];
}
