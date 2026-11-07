/* ─── 品牌配置（可通过 NEXT_PUBLIC_APP_* 环境变量覆盖，构建时内联） ─── */
export interface BrandConfig {
    name: string;
    tagline: string;
    storagePrefix: string;
}

export const brand: BrandConfig = {
    name: process.env.NEXT_PUBLIC_APP_NAME || '知识图解工作台',
    tagline: process.env.NEXT_PUBLIC_APP_TAGLINE || '把知识讲清楚',
    storagePrefix: 'sfa',
};
