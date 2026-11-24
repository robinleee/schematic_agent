// Design tokens：颜色 / 字体 / 圆角 / 控件高度 的唯一来源。
// CSS 侧的同名变量在 src/styles/global.css 的 :root 里；改色时两边一起改。
import { theme as antdTheme } from 'antd';
import type { ThemeConfig } from 'antd';

export const FONT_STACK =
  '"PingFang SC","HarmonyOS Sans SC","Microsoft YaHei",-apple-system,"Segoe UI",sans-serif';

/** 数字/英文可选回退（不加载 webfont：内网环境无外网字体） */
export const FONT_NUMERIC = `${FONT_STACK},"DM Sans"`;

export const palette = {
  primary: '#2f6bff',
  primaryHover: '#1f57e6',
  primarySoft: '#eef3ff',
  success: '#12b76a',
  warning: '#f79009',
  error: '#f04438',
  bg: '#f6f7f9',
  surface: '#ffffff',
  surfaceAlt: '#fafbfc',
  border: '#e6e8ec',
  borderStrong: '#d5d9e0',
  text: '#101828',
  textSecondary: '#475467',
  textTertiary: '#98a2b3',
  hover: '#f5f7fb',
};

const darkPalette = {
  primarySoft: 'rgba(47,107,255,0.18)',
  bg: '#0f1216',
  surface: '#171a21',
  surfaceAlt: '#1b1f27',
  border: '#262b35',
  borderStrong: '#333a46',
  text: '#e6e8ec',
  textSecondary: '#98a2b3',
  textTertiary: '#667085',
  hover: '#20252e',
};

export function buildTheme(dark: boolean): ThemeConfig {
  const p = dark ? { ...palette, ...darkPalette } : palette;

  return {
    algorithm: dark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
    token: {
      colorPrimary: palette.primary,
      colorInfo: palette.primary,
      colorSuccess: palette.success,
      colorWarning: palette.warning,
      colorError: palette.error,
      colorLink: palette.primary,
      colorBgLayout: p.bg,
      colorBgContainer: p.surface,
      colorBgElevated: p.surface,
      colorBorder: p.border,
      colorBorderSecondary: p.border,
      colorText: p.text,
      colorTextSecondary: p.textSecondary,
      colorTextTertiary: p.textTertiary,
      colorTextQuaternary: p.textTertiary,
      fontFamily: FONT_STACK,
      fontSize: 13,
      fontSizeSM: 12,
      fontSizeLG: 14,
      fontSizeHeading4: 20,
      fontSizeHeading5: 16,
      lineHeight: 1.55,
      borderRadius: 8,
      borderRadiusLG: 10,
      borderRadiusSM: 6,
      borderRadiusXS: 4,
      controlHeight: 36,
      controlHeightSM: 28,
      controlHeightLG: 40,
      controlOutline: dark ? 'rgba(47,107,255,0.28)' : 'rgba(47,107,255,0.14)',
      boxShadow: '0 1px 2px rgba(16,24,40,.04)',
      boxShadowSecondary: '0 8px 24px rgba(16,24,40,.12)',
      wireframe: false,
    },
    components: {
      Layout: {
        headerBg: p.surface,
        siderBg: p.surface,
        bodyBg: p.bg,
        headerHeight: 56,
        headerPadding: '0 24px',
      },
      Menu: {
        itemHeight: 36,
        itemBorderRadius: 8,
        itemMarginInline: 8,
        itemMarginBlock: 2,
        itemPaddingInline: 10,
        iconSize: 15,
        collapsedIconSize: 16,
        itemColor: p.textSecondary,
        itemHoverColor: p.text,
        itemHoverBg: p.hover,
        itemSelectedBg: p.primarySoft,
        itemSelectedColor: dark ? '#8fb2ff' : palette.primary,
        itemActiveBg: p.primarySoft,
        groupTitleColor: p.textTertiary,
        groupTitleFontSize: 11,
        darkItemBg: p.surface,
        darkSubMenuItemBg: p.surface,
        darkItemColor: p.textSecondary,
        darkItemHoverBg: p.hover,
        darkItemHoverColor: p.text,
        darkItemSelectedBg: p.primarySoft,
        darkItemSelectedColor: '#8fb2ff',
        darkGroupTitleColor: p.textTertiary,
        activeBarBorderWidth: 0,
      },
      Button: {
        controlHeight: 36,
        controlHeightSM: 28,
        fontSize: 13,
        paddingInline: 14,
        primaryShadow: 'none',
        defaultShadow: 'none',
        dangerShadow: 'none',
        fontWeight: 500,
      },
      Input: { controlHeight: 36, paddingInline: 12 },
      InputNumber: { controlHeight: 36 },
      Select: { controlHeight: 36, optionSelectedBg: p.primarySoft },
      Card: {
        borderRadiusLG: 10,
        paddingLG: 20,
        headerBg: 'transparent',
        headerFontSize: 14,
        colorBorderSecondary: p.border,
      },
      Table: {
        headerBg: dark ? '#1b1f27' : '#f9fafb',
        headerColor: p.textSecondary,
        headerSplitColor: 'transparent',
        borderColor: p.border,
        cellPaddingBlock: 10,
        cellPaddingInline: 12,
        rowHoverBg: p.hover,
        fontSize: 13,
      },
      Tag: { borderRadiusSM: 6, defaultBg: p.surfaceAlt, defaultColor: p.textSecondary },
      Segmented: {
        itemSelectedBg: p.surface,
        itemSelectedColor: p.text,
        trackBg: p.surfaceAlt,
        itemColor: p.textSecondary,
        trackPadding: 2,
      },
      Tabs: { horizontalItemGutter: 20, titleFontSize: 13, itemSelectedColor: p.text },
      Statistic: { contentFontSize: 24, titleFontSize: 12 },
      Tooltip: { borderRadius: 8 },
      Modal: { borderRadiusLG: 12 },
      Switch: { handleSize: 14 },
    },
  };
}

export default buildTheme;
