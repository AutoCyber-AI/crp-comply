#!/usr/bin/env python3
"""Accessibility, contrast, and UX fixes for CRP Comply frontend."""
import os
import re

SRC = os.path.join(os.path.dirname(__file__), "src")

def read_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def write_file(path, content):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

def apply(path, edits):
    """edits: list of (old, new, replace_all)"""
    full = os.path.join(SRC, path)
    content = read_file(full)
    for old, new, replace_all in edits:
        if replace_all:
            content = content.replace(old, new)
        else:
            if old not in content:
                print(f"WARNING: missing exact match in {path}")
                continue
            content = content.replace(old, new, 1)
    write_file(full, content)

# ═══════════════════════════════════════════════════════════════════
#  index.css
# ═══════════════════════════════════════════════════════════════════
apply("index.css", [
    (
        """  :focus-visible {
    outline: none;
    box-shadow: var(--crp-ring-focus);
    border-radius: var(--crp-r-sm);
  }""",
        """  :focus-visible {
    outline: 2px solid #9DAB34;
    outline-offset: 2px;
    box-shadow: none;
    border-radius: var(--crp-r-sm);
  }""",
        False,
    ),
])

# Append prefers-reduced-motion and sr-only
full = os.path.join(SRC, "index.css")
content = read_file(full)
if "prefers-reduced-motion" not in content:
    content += """

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
"""
    write_file(full, content)

# ═══════════════════════════════════════════════════════════════════
#  PublicLayout.tsx
# ═══════════════════════════════════════════════════════════════════
apply("components/PublicLayout.tsx", [
    (
        '<div className="min-h-screen bg-white">',
        '<div className="min-h-screen bg-white dark:bg-gray-900 text-gray-900 dark:text-white">',
        False,
    ),
])

# ═══════════════════════════════════════════════════════════════════
#  App.tsx
# ═══════════════════════════════════════════════════════════════════
apply("App.tsx", [
    (
        'import { Routes, Route, Navigate, useParams } from \'react-router-dom\'\nimport { useAuth } from \'@clerk/react\'',
        'import { useState, useEffect } from \'react\'\nimport { Routes, Route, Navigate, useParams, useLocation } from \'react-router-dom\'\nimport { useAuth } from \'@clerk/react\'',
        False,
    ),
    (
        'export default function App() {\n  return (\n    <Routes>',
        '''export default function App() {
  const location = useLocation()
  const [pageTitle, setPageTitle] = useState('')
  useEffect(() => {
    const titles: Record<string, string> = {
      '/app': 'Dashboard',
      '/app/draft': 'Draft',
      '/app/programme': 'Programme',
      '/app/recipes': 'Deliverables',
      '/app/vault': 'Vault',
      '/app/inbox': 'Inbox',
      '/app/settings': 'Settings',
      '/app/repositories': 'Repositories',
      '/app/no-code': 'No-Code Setup',
      '/app/guide': 'How it works',
      '/app/admin': 'Admin',
      '/pricing': 'Pricing',
      '/product': 'Product',
      '/free-assessment': 'Free Risk Check',
      '/docs': 'Docs',
      '/privacy': 'Privacy',
      '/terms': 'Terms',
      '/dpa': 'DPA',
      '/contact': 'Contact',
      '/sidecar': 'Sidecar',
    }
    setPageTitle(titles[location.pathname] || '')
  }, [location.pathname])

  return (
    <>
      <div className="sr-only" aria-live="polite" aria-atomic="true">{pageTitle}</div>
      <Routes>''',
        False,
    ),
    (
        '    </Routes>\n  )\n}',
        '    </Routes>\n    </>\n  )\n}',
        False,
    ),
])

# ═══════════════════════════════════════════════════════════════════
#  CreditPanel.tsx
# ═══════════════════════════════════════════════════════════════════
apply("components/CreditPanel.tsx", [
    (
        'rounded-full bg-brand-600 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider text-white',
        'rounded-full bg-brand-600 px-1.5 py-0.5 text-xs font-bold uppercase tracking-wider text-brand-900',
        False,
    ),
    (
        'rounded-full bg-amber-200 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber-900',
        'rounded-full bg-amber-200 px-2 py-0.5 text-xs font-semibold uppercase tracking-wider text-amber-900',
        False,
    ),
    (
        'inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-emerald-800',
        'inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold uppercase tracking-wider text-emerald-800',
        False,
    ),
    (
        'text-[11px] text-amber-700/80',
        'text-xs text-amber-700/80',
        False,
    ),
    (
        'mt-1 inline-flex items-center gap-1 text-[11px] font-medium text-brand-700 group-hover:underline',
        'mt-1 inline-flex items-center gap-1 text-sm font-medium text-brand-700 group-hover:underline',
        False,
    ),
    (
        'mt-2 text-[11px] text-gray-500',
        'mt-2 text-sm text-gray-600',
        False,
    ),
    (
        'mt-1 max-w-2xl text-sm text-gray-500',
        'mt-1 max-w-2xl text-sm text-gray-600',
        False,
    ),
])

# ═══════════════════════════════════════════════════════════════════
#  Pricing.tsx
# ═══════════════════════════════════════════════════════════════════
apply("pages/Pricing.tsx", [
    (
        'rounded-full bg-gradient-brand px-3 py-1 text-xs font-bold text-white shadow-md',
        'rounded-full bg-gradient-brand px-3 py-1 text-xs font-bold text-brand-900 shadow-md',
        False,
    ),
    (
        "tier.highlight\n                  ? 'bg-brand-600 text-white hover:bg-brand-500'\n                  : 'bg-gray-900 text-white hover:bg-gray-800'",
        "tier.highlight\n                  ? 'bg-brand-600 text-brand-900 hover:bg-brand-500'\n                  : 'bg-gray-900 text-white hover:bg-gray-800'",
        True,
    ),
    (
        'inline-block rounded-full bg-brand-50 px-2 py-0.5 text-[10px] font-medium text-brand-700',
        'inline-block rounded-full bg-brand-100 px-2 py-0.5 text-xs font-medium text-brand-900',
        False,
    ),
    (
        'text-[10px] font-bold uppercase tracking-wider text-gray-400 mb-1.5',
        'text-xs font-bold uppercase tracking-wider text-gray-600 mb-1.5',
        False,
    ),
    (
        'text-[11px] font-semibold uppercase tracking-wider text-emerald-700',
        'text-xs font-semibold uppercase tracking-wider text-emerald-700',
        False,
    ),
    (
        'text-[11px] text-gray-500 font-medium',
        'text-xs text-gray-600 font-medium',
        False,
    ),
    (
        'text-sm text-gray-400 mt-1',
        'text-sm text-gray-600 mt-1',
        False,
    ),
    (
        "          <div className=\"inline-flex items-center gap-2 text-xs text-gray-500\">\n            <Info size={12} />\n            Prices in USD.",
        "          <div className=\"inline-flex items-center gap-2 text-xs text-gray-600\">\n            <Info size={12} />\n            Prices in USD.",
        False,
    ),
    (
        '        <span className="text-sm text-gray-500">{displayPeriod}</span>',
        '        <span className="text-sm text-gray-600">{displayPeriod}</span>',
        False,
    ),
    (
        '      <p className="text-xs text-gray-500 mb-4">{tier.audience}</p>',
        '      <p className="text-xs text-gray-600 mb-4">{tier.audience}</p>',
        False,
    ),
    (
        '        <div className="text-xs text-gray-500 mt-0.5">{tier.overage}</div>',
        '        <div className="text-xs text-gray-600 mt-0.5">{tier.overage}</div>',
        False,
    ),
    (
        '        <span className="text-sm text-gray-500">/mo</span>',
        '        <span className="text-sm text-gray-600">/mo</span>',
        False,
    ),
    (
        "        <span className={`text-sm font-medium ${period === 'monthly' ? 'text-gray-900' : 'text-gray-500'}`}>",
        "        <span className={`text-sm font-medium ${period === 'monthly' ? 'text-gray-900' : 'text-gray-600'}`}>",
        False,
    ),
    (
        "        <span className={`text-sm font-medium ${period === 'annual' ? 'text-gray-900' : 'text-gray-500'}`}>",
        "        <span className={`text-sm font-medium ${period === 'annual' ? 'text-gray-900' : 'text-gray-600'}`}>",
        False,
    ),
    (
        '        <div className="mt-4 text-sm text-gray-500 max-w-2xl mx-auto">',
        '        <div className="mt-4 text-sm text-gray-600 max-w-2xl mx-auto">',
        False,
    ),
])

# ═══════════════════════════════════════════════════════════════════
#  Dashboard.tsx
# ═══════════════════════════════════════════════════════════════════
apply("pages/Dashboard.tsx", [
    (
        'rounded-2xl bg-gradient-to-br from-brand-600 via-brand-700 to-brand-900 p-8 text-white overflow-hidden',
        'rounded-2xl bg-gradient-to-br from-brand-600 via-brand-700 to-brand-900 p-8 text-brand-900 overflow-hidden',
        False,
    ),
    (
        'text-sm font-medium text-brand-200',
        'text-sm font-medium text-brand-800',
        False,
    ),
    (
        'text-brand-200 text-sm max-w-xl',
        'text-brand-800 text-sm max-w-xl',
        False,
    ),
    (
        'inline-flex items-center gap-2 bg-white/10 backdrop-blur-sm rounded-full px-4 py-1.5 text-sm',
        'inline-flex items-center gap-2 bg-white/90 backdrop-blur-sm rounded-full px-4 py-1.5 text-sm text-gray-900',
        False,
    ),
    (
        'inline-flex items-center gap-1.5 bg-white/10 backdrop-blur-sm rounded-full px-3 py-1.5 text-xs',
        'inline-flex items-center gap-1.5 bg-white/90 backdrop-blur-sm rounded-full px-3 py-1.5 text-xs text-gray-900',
        False,
    ),
    (
        'stat-card bg-gradient-to-br ${stat.gradient} text-white animate-slide-up',
        'stat-card bg-gradient-to-br ${stat.gradient} text-gray-900 animate-slide-up',
        False,
    ),
    (
        'text-xs font-medium text-white/70',
        'text-xs font-medium text-gray-700',
        False,
    ),
    (
        'Icon className="h-5 w-5 text-white"',
        'Icon className="h-5 w-5 text-gray-900"',
        False,
    ),
    (
        'font-mono text-gray-500 text-xs',
        'font-mono text-gray-600 text-xs',
        True,
    ),
    (
        'text-xs text-gray-500',
        'text-xs text-gray-600',
        True,
    ),
])

# ═══════════════════════════════════════════════════════════════════
#  Reports.tsx
# ═══════════════════════════════════════════════════════════════════
apply("pages/Reports.tsx", [
    (
        '<label className="text-sm text-slate-600">Filter by kind:</label>',
        '<label htmlFor="kind-filter" className="text-sm text-slate-600">Filter by kind:</label>',
        False,
    ),
    (
        '<select\n              value={kindFilter}',
        '<select\n              id="kind-filter"\n              value={kindFilter}',
        False,
    ),
    (
        'title="Delete report"',
        'aria-label="Delete report" title="Delete report"',
        False,
    ),
    (
        '<button\n          onClick={onDelete}\n          disabled={deleting}\n          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm text-rose-600 border border-rose-200 rounded-md hover:bg-rose-50 disabled:opacity-50"\n        >\n          <Trash2 className="w-4 h-4" />\n        </button>',
        '<button\n          onClick={onDelete}\n          disabled={deleting}\n          aria-label="Delete evidence pack"\n          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm text-rose-600 border border-rose-200 rounded-md hover:bg-rose-50 disabled:opacity-50"\n        >\n          <Trash2 className="w-4 h-4" />\n        </button>',
        False,
    ),
    (
        '<table className="w-full text-sm min-w-[640px]">\n                <thead className="bg-slate-50 text-left text-slate-600 uppercase text-xs tracking-wide">\n                  <tr>\n                    <th className="px-4 py-3">Kind</th>',
        '<table className="w-full text-sm min-w-[640px]">\n                <caption className="sr-only">Compliance reports</caption>\n                <thead className="bg-slate-50 text-left text-slate-600 uppercase text-xs tracking-wide">\n                  <tr>\n                    <th className="px-4 py-3" scope="col">Kind</th>',
        False,
    ),
    (
        '<th className="px-4 py-3">System</th>',
        '<th className="px-4 py-3" scope="col">System</th>',
        False,
    ),
    (
        '<th className="px-4 py-3">Risk</th>',
        '<th className="px-4 py-3" scope="col">Risk</th>',
        False,
    ),
    (
        '<th className="px-4 py-3">Generated</th>',
        '<th className="px-4 py-3" scope="col">Generated</th>',
        False,
    ),
    (
        '<th className="px-4 py-3">Size</th>',
        '<th className="px-4 py-3" scope="col">Size</th>',
        False,
    ),
    (
        '<th className="px-4 py-3 text-right">Actions</th>',
        '<th className="px-4 py-3 text-right" scope="col">Actions</th>',
        False,
    ),
    (
        'bg-brand-600 text-white rounded-md hover:bg-brand-700',
        'bg-brand-600 text-brand-900 rounded-md hover:bg-brand-700',
        False,
    ),
    (
        'bg-brand-600 text-white rounded hover:bg-brand-700',
        'bg-brand-600 text-brand-900 rounded hover:bg-brand-700',
        True,
    ),
    (
        'text-[11px] text-slate-400 mt-0.5 font-mono',
        'text-xs text-slate-600 mt-0.5 font-mono',
        False,
    ),
    (
        'text-slate-400 text-xs',
        'text-slate-600 text-xs',
        False,
    ),
    (
        'text-xs text-slate-400',
        'text-xs text-slate-600',
        False,
    ),
    (
        'border-transparent text-slate-500 hover:text-slate-700',
        'border-transparent text-slate-600 hover:text-slate-700',
        True,
    ),
    (
        'ml-auto text-xs text-slate-500',
        'ml-auto text-xs text-slate-600',
        False,
    ),
    (
        'text-center py-12 text-slate-500',
        'text-center py-12 text-slate-600',
        True,
    ),
    (
        'text-xs text-slate-500 mt-1',
        'text-xs text-slate-600 mt-1',
        False,
    ),
    (
        'text-sm text-slate-500 mb-4',
        'text-sm text-slate-600 mb-4',
        False,
    ),
])

# ═══════════════════════════════════════════════════════════════════
#  Repositories.tsx
# ═══════════════════════════════════════════════════════════════════
apply("pages/Repositories.tsx", [
    (
        '<div className="mb-6 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-900/20 dark:text-red-300">',
        '<div className="mb-6 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-900/20 dark:text-red-300" role="alert">',
        False,
    ),
    (
        'bg-brand-600 text-white hover:bg-brand-500',
        'bg-brand-600 text-brand-900 hover:bg-brand-500',
        True,
    ),
    (
        'text-xs text-gray-500 dark:text-gray-400',
        'text-xs text-gray-600 dark:text-gray-400',
        False,
    ),
    (
        'text-center py-12 text-gray-500',
        'text-center py-12 text-gray-600',
        False,
    ),
])

# ═══════════════════════════════════════════════════════════════════
#  Settings.tsx
# ═══════════════════════════════════════════════════════════════════
apply("pages/Settings.tsx", [
    (
        "'flex items-center gap-1.5 whitespace-nowrap rounded-lg px-3 py-1.5 text-xs font-medium transition-colors',",
        "'flex items-center gap-1.5 whitespace-nowrap rounded-lg px-3 py-2 text-xs font-medium transition-colors',",
        False,
    ),
    (
        '<form onSubmit={handleCreate} className="flex gap-2 mb-4">\n        <input\n          type="text"\n          className="input flex-1"\n          placeholder="Key name (e.g. \'my-laptop\', \'staging\')"',
        '<form onSubmit={handleCreate} className="flex gap-2 mb-4">\n        <label htmlFor="api-key-name" className="sr-only">Key name</label>\n        <input\n          id="api-key-name"\n          type="text"\n          className="input flex-1"\n          placeholder="Key name (e.g. \'my-laptop\', \'staging\')"',
        False,
    ),
    (
        '<button\n              onClick={() => handleCopy(newKey)}\n              className="btn-secondary text-xs py-1 px-2"\n            >\n              {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}\n            </button>',
        '<button\n              onClick={() => handleCopy(newKey)}\n              aria-label={copied ? \'Copied\' : \'Copy key\'}\n              className="btn-secondary text-xs py-1 px-2"\n            >\n              {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}\n            </button>',
        False,
    ),
    (
        '<button\n                      onClick={() => revokeMutation.mutate(k.id)}\n                      disabled={revokeMutation.isPending}\n                      className="text-red-600 hover:text-red-800"\n                      title="Revoke key"\n                    >\n                      <Trash2 className="h-4 w-4" />\n                    </button>',
        '<button\n                      onClick={() => revokeMutation.mutate(k.id)}\n                      disabled={revokeMutation.isPending}\n                      className="text-red-600 hover:text-red-800"\n                      title="Revoke key"\n                      aria-label="Revoke key"\n                    >\n                      <Trash2 className="h-4 w-4" />\n                    </button>',
        False,
    ),
    (
        '<div className="mt-5 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">',
        '<div className="mt-5 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800" role="alert">',
        False,
    ),
    (
        '<div className="mt-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">',
        '<div className="mt-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800" role="alert">',
        False,
    ),
    (
        '<div className="mb-4 p-3 rounded-lg bg-green-50 border border-green-200">',
        '<div className="mb-4 p-3 rounded-lg bg-green-50 border border-green-200" role="status">',
        False,
    ),
    (
        '<div className="rounded-md bg-emerald-50 border border-emerald-200 px-3 py-2 text-xs text-emerald-800">',
        '<div className="rounded-md bg-emerald-50 border border-emerald-200 px-3 py-2 text-xs text-emerald-800" role="status">',
        False,
    ),
    (
        '<div className="rounded-md bg-red-50 border border-red-200 px-3 py-2 text-xs text-red-800">',
        '<div className="rounded-md bg-red-50 border border-red-200 px-3 py-2 text-xs text-red-800" role="alert">',
        False,
    ),
    (
        '''<div
              className={
                testMut.data.success
                  ? 'rounded-md bg-emerald-50 border border-emerald-200 px-3 py-2 text-xs text-emerald-800'
                  : 'rounded-md bg-red-50 border border-red-200 px-3 py-2 text-xs text-red-800'
              }
            >''',
        '''<div
              className={
                testMut.data.success
                  ? 'rounded-md bg-emerald-50 border border-emerald-200 px-3 py-2 text-xs text-emerald-800'
                  : 'rounded-md bg-red-50 border border-red-200 px-3 py-2 text-xs text-red-800'
              }
              role={testMut.data.success ? 'status' : 'alert'}
            >''',
        False,
    ),
    (
        '<table className="w-full text-sm min-w-[560px]">\n            <thead className="bg-gray-50">\n              <tr>\n                <th className="text-left px-4 py-2 font-medium text-gray-700">Name</th>',
        '<table className="w-full text-sm min-w-[560px]">\n            <caption className="sr-only">Your API keys</caption>\n            <thead className="bg-gray-50">\n              <tr>\n                <th className="text-left px-4 py-2 font-medium text-gray-700" scope="col">Name</th>',
        False,
    ),
    (
        '<th className="text-left px-4 py-2 font-medium text-gray-700">Tier</th>',
        '<th className="text-left px-4 py-2 font-medium text-gray-700" scope="col">Tier</th>',
        False,
    ),
    (
        '<th className="text-left px-4 py-2 font-medium text-gray-700">Prefix</th>',
        '<th className="text-left px-4 py-2 font-medium text-gray-700" scope="col">Prefix</th>',
        False,
    ),
    (
        '<th className="text-left px-4 py-2 font-medium text-gray-700">Created</th>',
        '<th className="text-left px-4 py-2 font-medium text-gray-700" scope="col">Created</th>',
        False,
    ),
    (
        '<th className="text-right px-4 py-2 font-medium text-gray-700">Actions</th>',
        '<th className="text-right px-4 py-2 font-medium text-gray-700" scope="col">Actions</th>',
        False,
    ),
    (
        'rounded-full px-2.5 py-1 text-[10px] font-bold',
        'rounded-full px-2.5 py-1 text-xs font-bold',
        False,
    ),
    (
        'bg-red-50 px-2 py-0.5 text-[10px] font-bold text-red-700',
        'bg-red-50 px-2 py-0.5 text-xs font-bold text-red-700',
        False,
    ),
    (
        'bg-amber-50 px-2 py-0.5 text-[10px] font-bold text-amber-700',
        'bg-amber-50 px-2 py-0.5 text-xs font-bold text-amber-700',
        False,
    ),
    (
        'bg-brand-50 border border-brand-200 px-2 py-0.5 text-[10px] font-semibold text-brand-700',
        'bg-brand-100 border border-brand-200 px-2 py-0.5 text-xs font-semibold text-brand-900',
        False,
    ),
    (
        'text-[11px] font-medium text-emerald-700',
        'text-xs font-medium text-emerald-700',
        False,
    ),
    (
        'text-[11px] font-medium text-gray-600',
        'text-xs font-medium text-gray-600',
        False,
    ),
    (
        'text-[11px] font-medium uppercase tracking-wide text-gray-500',
        'text-xs font-medium uppercase tracking-wide text-gray-600',
        False,
    ),
    (
        'text-[11px] font-bold uppercase tracking-wider ${tierBadge.label}',
        'text-xs font-bold uppercase tracking-wider ${tierBadge.label}',
        False,
    ),
    (
        'text-[11px] font-bold uppercase tracking-wider text-gray-500',
        'text-xs font-bold uppercase tracking-wider text-gray-600',
        False,
    ),
    (
        'font-mono text-[11px] mt-0.5',
        'font-mono text-xs mt-0.5',
        True,
    ),
    (
        'text-[11px] font-semibold uppercase tracking-wider text-brand-700',
        'text-xs font-semibold uppercase tracking-wider text-brand-700',
        False,
    ),
    (
        'text-xs text-gray-400',
        'text-xs text-gray-600',
        True,
    ),
    (
        'text-gray-400',
        'text-gray-600',
        True,
    ),
])

# Global text-gray-500 in Settings.tsx (safe: no dark variants)
full = os.path.join(SRC, "pages/Settings.tsx")
content = read_file(full)
content = content.replace("text-gray-500", "text-gray-600")
write_file(full, content)

# ═══════════════════════════════════════════════════════════════════
#  AppShell.tsx
# ═══════════════════════════════════════════════════════════════════
apply("components/AppShell.tsx", [
    (
        'import { NavLink, Outlet, useNavigate } from \'react-router-dom\'',
        'import { NavLink, Outlet, useNavigate, useMatch } from \'react-router-dom\'',
        False,
    ),
    (
        'import { useEffect, useState } from \'react\'',
        'import { useEffect, useState, useRef } from \'react\'',
        False,
    ),
    (
        'export default function AppShell() {',
        '''function AccessibleNavLink({ to, end, className, children, ...rest }: React.ComponentProps<typeof NavLink>) {
  const match = useMatch({ path: typeof to === 'string' ? to : to.pathname ?? '', end: end ?? false })
  return (
    <NavLink to={to} end={end} className={className} aria-current={match ? 'page' : undefined} {...rest}>
      {children}
    </NavLink>
  )
}

export default function AppShell() {''',
        False,
    ),
    (
        '  const [moreOpen, setMoreOpen] = useState(false)\n  const [mobileOpen, setMobileOpen] = useState(false)',
        '  const [moreOpen, setMoreOpen] = useState(false)\n  const [mobileOpen, setMobileOpen] = useState(false)\n  const closeBtnRef = useRef<HTMLButtonElement>(null)',
        False,
    ),
])

# Add useEffects for mobile focus and Escape
full = os.path.join(SRC, "components/AppShell.tsx")
content = read_file(full)

# Insert focus + escape effects before toggleDark
focus_esc_effects = '''  useEffect(() => {
    if (mobileOpen) {
      closeBtnRef.current?.focus()
    }
  }, [mobileOpen])

  useEffect(() => {
    if (!mobileOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setMobileOpen(false)
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [mobileOpen])

'''
content = content.replace('  const toggleDark = () => {', focus_esc_effects + '  const toggleDark = () => {')

# Replace NavLink tags with AccessibleNavLink
content = content.replace('<NavLink', '<AccessibleNavLink')
content = content.replace('</NavLink>', '</AccessibleNavLink>')

# Add end prop to the two "← Site" links
content = content.replace(
    '<AccessibleNavLink\n            to="/"\n            className="text-xs font-medium text-ink-3 hover:text-ink transition-colors"\n            title="Back to public site"',
    '<AccessibleNavLink\n            to="/"\n            end\n            className="text-xs font-medium text-ink-3 hover:text-ink transition-colors"\n            title="Back to public site"'
)
content = content.replace(
    '<AccessibleNavLink\n            to="/"\n            className="lg:hidden text-xs font-medium text-ink-3 hover:text-ink transition-colors"\n            title="Back to public site"',
    '<AccessibleNavLink\n            to="/"\n            end\n            className="lg:hidden text-xs font-medium text-ink-3 hover:text-ink transition-colors"\n            title="Back to public site"'
)

# Increase nav item padding py-2 -> py-3
content = content.replace("px-3 py-2 text-sm font-medium transition-colors duration-crp ease-crp", "px-3 py-3 text-sm font-medium transition-colors duration-crp ease-crp")
content = content.replace("px-3 py-2 text-sm font-medium transition-colors", "px-3 py-3 text-sm font-medium transition-colors")
content = content.replace("w-full group flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors duration-crp ease-crp", "w-full group flex items-center gap-3 rounded-md px-3 py-3 text-sm font-medium transition-colors duration-crp ease-crp")

# Mobile menu button size
content = content.replace(
    'onClick={() => setMobileOpen(true)}\n            className="lg:hidden p-2 -ml-2 rounded-md hover:bg-surface-2"\n            aria-label="Open navigation menu"',
    'onClick={() => setMobileOpen(true)}\n            className="lg:hidden h-10 w-10 flex items-center justify-center -ml-2 rounded-md hover:bg-surface-2"\n            aria-label="Open navigation menu"'
)

# Dark mode toggle size
content = content.replace(
    'className="p-1.5 rounded-md text-ink-3 hover:bg-surface-2 transition-colors focus:outline-none focus:ring-2 focus:ring-primary"\n                  aria-label={dark ? \'Switch to light mode\' : \'Switch to dark mode\'}',
    'className="h-10 w-10 flex items-center justify-center rounded-md text-ink-3 hover:bg-surface-2 transition-colors focus:outline-none focus:ring-2 focus:ring-primary"\n                  aria-label={dark ? \'Switch to light mode\' : \'Switch to dark mode\'}'
)

# Help button size
content = content.replace(
    'className="p-2 rounded-md text-ink-3 hover:text-ink hover:bg-surface-2 focus:outline-none focus:ring-2 focus:ring-primary"\n              aria-label="Open the getting-started guide"',
    'className="h-10 w-10 flex items-center justify-center rounded-md text-ink-3 hover:text-ink hover:bg-surface-2 focus:outline-none focus:ring-2 focus:ring-primary"\n              aria-label="Open the getting-started guide"'
)

# text-[10px] and text-[11px] in AppShell
content = content.replace('text-[10px] font-mono text-ink-4', 'text-xs font-mono text-ink-4')
content = content.replace('text-[11px] font-semibold', 'text-xs font-semibold')

write_file(full, content)

# ═══════════════════════════════════════════════════════════════════
#  PublicHeader.tsx — rewrite with mobile drawer + aria-current
# ═══════════════════════════════════════════════════════════════════
public_header_new = '''import { NavLink, useLocation } from 'react-router-dom'
import { SignInButton, SignUpButton, Show } from '@clerk/react'
import { Shield, Zap, Lock, Menu, X } from 'lucide-react'
import { useState } from 'react'

const navLinks = [
  { name: 'Product', href: '/product' },
  { name: 'Pricing', href: '/pricing' },
  { name: 'Free Risk Check', href: '/free-assessment' },
  { name: 'Docs', href: '/docs', external: false },
]

export default function PublicHeader() {
  const location = useLocation()
  const [mobileOpen, setMobileOpen] = useState(false)

  return (
    <header className="sticky top-0 z-40 w-full bg-white/80 backdrop-blur-md border-b border-gray-100 dark:bg-gray-900/80 dark:border-gray-800">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="flex h-16 items-center justify-between">
          <NavLink to="/" className="flex items-center gap-2.5" aria-current={location.pathname === '/' ? 'page' : undefined}>
            <div
              className="w-9 h-9 rounded-lg flex items-center justify-center"
              style={{ background: '#0B0B0C' }}
            >
              <img src="/crp-mark.png" alt="" aria-hidden="true" className="h-7 w-7" draggable={false} />
            </div>
            <div className="flex items-baseline gap-2">
              <span className="text-lg font-bold text-gray-900 tracking-tight dark:text-white">CRP Comply</span>
              <span className="hidden sm:inline text-xs text-gray-600 font-medium uppercase tracking-[0.14em] dark:text-gray-400">AI Governance</span>
            </div>
          </NavLink>

          <nav className="hidden md:flex items-center gap-6">
            {navLinks.map((l) => (
              <NavLink
                key={l.name}
                to={l.href}
                className="text-sm font-medium text-gray-600 hover:text-gray-900 transition-colors dark:text-gray-300 dark:hover:text-white"
                aria-current={location.pathname === l.href ? 'page' : undefined}
              >
                {l.name}
              </NavLink>
            ))}
          </nav>

          <div className="flex items-center gap-2">
            <button
              onClick={() => setMobileOpen(!mobileOpen)}
              className="md:hidden h-10 w-10 flex items-center justify-center rounded-md hover:bg-gray-100 dark:hover:bg-gray-800"
              aria-label={mobileOpen ? 'Close menu' : 'Open menu'}
              aria-expanded={mobileOpen}
              aria-controls="public-mobile-menu"
            >
              {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </button>
            <Show when="signed-out">
              <div className="hidden md:flex items-center gap-2">
                <SignInButton mode="modal">
                  <button className="text-sm font-medium text-gray-700 hover:text-gray-900 px-3 py-2 dark:text-gray-300 dark:hover:text-white">
                    Sign in
                  </button>
                </SignInButton>
                <SignUpButton mode="modal">
                  <button className="btn-primary text-sm">Get started free</button>
                </SignUpButton>
              </div>
            </Show>
            <Show when="signed-in">
              <NavLink to="/app" className="btn-primary text-sm hidden md:inline-flex">
                Open app →
              </NavLink>
            </Show>
          </div>
        </div>
      </div>

      {/* Mobile drawer */}
      {mobileOpen && (
        <>
          <div
            className="fixed inset-0 bg-black/20 z-30 md:hidden"
            onClick={() => setMobileOpen(false)}
            aria-hidden="true"
          />
          <nav
            id="public-mobile-menu"
            className="fixed top-16 left-0 right-0 bg-white border-b border-gray-100 shadow-lg z-40 md:hidden dark:bg-gray-900 dark:border-gray-800"
          >
            <div className="mx-auto max-w-7xl px-4 py-4 space-y-2">
              {navLinks.map((l) => (
                <NavLink
                  key={l.name}
                  to={l.href}
                  onClick={() => setMobileOpen(false)}
                  className="block px-3 py-3 text-base font-medium text-gray-700 hover:bg-gray-50 rounded-md dark:text-gray-200 dark:hover:bg-gray-800"
                  aria-current={location.pathname === l.href ? 'page' : undefined}
                >
                  {l.name}
                </NavLink>
              ))}
              <div className="pt-2 border-t border-gray-100 dark:border-gray-800 flex flex-col gap-2">
                <Show when="signed-out">
                  <SignInButton mode="modal">
                    <button className="w-full text-left px-3 py-3 text-base font-medium text-gray-700 hover:bg-gray-50 rounded-md dark:text-gray-200 dark:hover:bg-gray-800">
                      Sign in
                    </button>
                  </SignInButton>
                  <SignUpButton mode="modal">
                    <button className="btn-primary w-full text-sm">Get started free</button>
                  </SignUpButton>
                </Show>
                <Show when="signed-in">
                  <NavLink to="/app" onClick={() => setMobileOpen(false)} className="btn-primary text-sm text-center">
                    Open app →
                  </NavLink>
                </Show>
              </div>
            </div>
          </nav>
        </>
      )}
    </header>
  )
}

export function PublicFooter() {
  return (
    <footer className="border-t border-gray-100 bg-white mt-24 dark:bg-gray-900 dark:border-gray-800">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-12">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-8">
          <div className="md:col-span-2">
            <div className="flex items-center gap-2.5 mb-3">
              <div
                className="w-9 h-9 rounded-lg flex items-center justify-center"
                style={{ background: '#0B0B0C' }}
              >
                <img src="/crp-mark.png" alt="" aria-hidden="true" className="h-7 w-7" draggable={false} />
              </div>
              <span className="text-lg font-bold text-gray-900 tracking-tight dark:text-white">CRP Comply</span>
            </div>
            <p className="text-sm text-gray-600 max-w-sm dark:text-gray-300">
              Tamper-evident AI compliance for the EU AI Act, GDPR, and ISO 42001. Powered by the{' '}
              <a
                href="https://www.crprotocol.io"
                target="_blank"
                rel="noopener noreferrer"
                className="text-brand-700 hover:text-brand-900 underline-offset-2 hover:underline font-medium dark:text-brand-400 dark:hover:text-brand-300"
              >
                Context Relay Protocol
              </a>
              .
            </p>
            <div className="flex items-center gap-3 mt-4">
              <Badge icon={<Shield className="w-3.5 h-3.5" />} label="EU AI Act ready" />
              <Badge icon={<Lock className="w-3.5 h-3.5" />} label="SOC 2 roadmap" />
            </div>
          </div>
          <div>
            <h4 className="text-sm font-semibold text-gray-900 mb-3 dark:text-white">Product</h4>
            <ul className="space-y-2 text-sm">
              <li><NavLink to="/pricing" className="text-gray-600 hover:text-gray-900 dark:text-gray-300 dark:hover:text-white">Pricing</NavLink></li>
              <li><NavLink to="/free-assessment" className="text-gray-600 hover:text-gray-900 dark:text-gray-300 dark:hover:text-white">Free Risk Check</NavLink></li>
              <li><a href="https://crprotocol.io" className="text-gray-600 hover:text-gray-900 dark:text-gray-300 dark:hover:text-white">CRP Protocol</a></li>
            </ul>
          </div>
          <div>
            <h4 className="text-sm font-semibold text-gray-900 mb-3 dark:text-white">Legal</h4>
            <ul className="space-y-2 text-sm">
              <li><a href="/privacy" className="text-gray-600 hover:text-gray-900 dark:text-gray-300 dark:hover:text-white">Privacy</a></li>
              <li><a href="/terms" className="text-gray-600 hover:text-gray-900 dark:text-gray-300 dark:hover:text-white">Terms</a></li>
              <li><a href="/dpa" className="text-gray-600 hover:text-gray-900 dark:text-gray-300 dark:hover:text-white">DPA</a></li>
              <li><a href="/contact" className="text-gray-600 hover:text-gray-900 dark:text-gray-300 dark:hover:text-white">Contact</a></li>
            </ul>
          </div>
        </div>
        <div className="mt-10 pt-6 border-t border-gray-100 text-xs text-gray-600 flex items-center justify-between dark:border-gray-800 dark:text-gray-400">
          <span>© 2026 AutoCyber AI Pty Ltd. All rights reserved.</span>
          <span className="flex items-center gap-1.5">
            <Zap className="w-3.5 h-3.5 text-brand-600" />
            Powered by{' '}
            <a
              href="https://www.crprotocol.io"
              target="_blank"
              rel="noopener noreferrer"
              className="text-brand-700 hover:text-brand-900 underline-offset-2 hover:underline font-medium dark:text-brand-400 dark:hover:text-brand-300"
            >
              Context Relay Protocol
            </a>
          </span>
        </div>
      </div>
    </footer>
  )
}

function Badge({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-gray-100 px-2.5 py-1 text-xs font-medium text-gray-700 dark:bg-gray-800 dark:text-gray-300">
      {icon}
      {label}
    </span>
  )
}
'''
write_file(os.path.join(SRC, "components/PublicHeader.tsx"), public_header_new)

# ═══════════════════════════════════════════════════════════════════
#  Landing.tsx
# ═══════════════════════════════════════════════════════════════════
apply("pages/Landing.tsx", [
    (
        "import { NavLink } from 'react-router-dom'",
        "import { NavLink, useLocation } from 'react-router-dom'",
        False,
    ),
    (
        'export default function Landing() {',
        'export default function Landing() {\n  const location = useLocation()',
        False,
    ),
    (
        'text-xs uppercase tracking-wider text-gray-500',
        'text-xs uppercase tracking-wider text-gray-600',
        False,
    ),
    (
        'text-sm text-gray-500',
        'text-sm text-gray-600',
        False,
    ),
    (
        'text-sm text-gray-400 mt-1',
        'text-sm text-gray-600 mt-1',
        False,
    ),
    (
        'text-xs font-mono text-gray-400',
        'text-xs font-mono text-gray-600',
        False,
    ),
    (
        'inline-flex items-center rounded-full bg-brand-50 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wider text-brand-700 ring-1 ring-brand-200',
        'inline-flex items-center rounded-full bg-brand-100 px-2 py-0.5 text-xs font-semibold uppercase tracking-wider text-brand-900 ring-1 ring-brand-200',
        False,
    ),
    (
        'inline-flex items-center gap-1 rounded-full bg-brand-600 px-2.5 py-0.5 text-[11px] font-semibold text-white mb-3',
        'inline-flex items-center gap-1 rounded-full bg-brand-600 px-2.5 py-0.5 text-xs font-semibold text-brand-900 mb-3',
        False,
    ),
    (
        'bg-gradient-brand text-white',
        'bg-gradient-brand text-brand-900',
        False,
    ),
])

# Add aria-current to Landing NavLinks
full = os.path.join(SRC, "pages/Landing.tsx")
content = read_file(full)
# NavLink to free-assessment
content = content.replace(
    '<NavLink\n                to="/free-assessment"\n                className="inline-flex items-center justify-center gap-2 rounded-lg bg-gray-900 px-6 py-3.5 text-base font-semibold text-white shadow-lg hover:bg-gray-800 transition-all active:scale-[0.98]"',
    '<NavLink\n                to="/free-assessment"\n                aria-current={location.pathname === \'/free-assessment\' ? \'page\' : undefined}\n                className="inline-flex items-center justify-center gap-2 rounded-lg bg-gray-900 px-6 py-3.5 text-base font-semibold text-white shadow-lg hover:bg-gray-800 transition-all active:scale-[0.98]"'
)
content = content.replace(
    '<NavLink to="/docs#local-llm" className="underline font-semibold ml-1">',
    '<NavLink to="/docs#local-llm" aria-current={location.pathname === \'/docs\' ? \'page\' : undefined} className="underline font-semibold ml-1">'
)
content = content.replace(
    '<NavLink to="/pricing" className="inline-flex items-center gap-2 text-brand-700 font-semibold hover:text-brand-800">',
    '<NavLink to="/pricing" aria-current={location.pathname === \'/pricing\' ? \'page\' : undefined} className="inline-flex items-center gap-2 text-brand-700 font-semibold hover:text-brand-800">'
)
content = content.replace(
    '<NavLink\n              to="/free-assessment"\n              className="inline-flex items-center justify-center gap-2 rounded-lg bg-white px-6 py-3.5 text-base font-semibold text-gray-900 shadow-lg hover:bg-gray-50 transition-all active:scale-[0.98]"',
    '<NavLink\n              to="/free-assessment"\n              aria-current={location.pathname === \'/free-assessment\' ? \'page\' : undefined}\n              className="inline-flex items-center justify-center gap-2 rounded-lg bg-white px-6 py-3.5 text-base font-semibold text-gray-900 shadow-lg hover:bg-gray-50 transition-all active:scale-[0.98]"'
)
write_file(full, content)

# ═══════════════════════════════════════════════════════════════════
#  Onboarding.tsx
# ═══════════════════════════════════════════════════════════════════
apply("pages/v2/Onboarding.tsx", [
    (
        '<button\n      type="button"\n      onClick={() => onChange(!value)}',
        '<button\n      type="button"\n      role="switch"\n      aria-checked={!!value}\n      onClick={() => onChange(!value)}',
        False,
    ),
    (
        '<textarea\n        className="input min-h-[140px]"\n        value={text}\n        onChange={(e) => setText(e.target.value)}',
        '<label htmlFor="onboarding-describe" className="sr-only">Describe your business</label>\n      <textarea\n        id="onboarding-describe"\n        className="input min-h-[140px]"\n        value={text}\n        onChange={(e) => setText(e.target.value)}',
        False,
    ),
])

# ═══════════════════════════════════════════════════════════════════
#  v2/Dashboard.tsx
# ═══════════════════════════════════════════════════════════════════
apply("pages/v2/Dashboard.tsx", [
    (
        '<StatusChip status="passed" />',
        '<StatusChip status="pending" />',
        False,
    ),
    (
        'text-[10px] uppercase tracking-wider text-ink-3',
        'text-xs uppercase tracking-wider text-ink-3',
        False,
    ),
])

# ═══════════════════════════════════════════════════════════════════
#  Layout.tsx
# ═══════════════════════════════════════════════════════════════════
apply("components/Layout.tsx", [
    (
        "import { NavLink, Outlet } from 'react-router-dom'",
        "import { NavLink, Outlet, useMatch } from 'react-router-dom'",
        False,
    ),
    (
        'export default function Layout() {',
        '''function AccessibleNavLink({ to, end, className, children, ...rest }: React.ComponentProps<typeof NavLink>) {
  const match = useMatch({ path: typeof to === 'string' ? to : to.pathname ?? '', end: end ?? false })
  return (
    <NavLink to={to} end={end} className={className} aria-current={match ? 'page' : undefined} {...rest}>
      {children}
    </NavLink>
  )
}

export default function Layout() {''',
        False,
    ),
    (
        'text-[11px] text-gray-500 font-medium uppercase tracking-[0.14em]',
        'text-xs text-gray-600 font-medium uppercase tracking-[0.14em]',
        False,
    ),
    (
        'text-[11px] font-medium text-brand-500 uppercase tracking-wider',
        'text-xs font-medium text-brand-500 uppercase tracking-wider',
        False,
    ),
])

full = os.path.join(SRC, "components/Layout.tsx")
content = read_file(full)
content = content.replace('<NavLink', '<AccessibleNavLink')
content = content.replace('</NavLink>', '</AccessibleNavLink>')
write_file(full, content)

# ═══════════════════════════════════════════════════════════════════
#  RuntimeToggle.tsx
# ═══════════════════════════════════════════════════════════════════
apply("components/RuntimeToggle.tsx", [
    (
        'h-9 px-2.5 rounded-md text-xs font-medium border border-hairline',
        'h-10 px-2.5 rounded-md text-xs font-medium border border-hairline',
        False,
    ),
    (
        'text-[10px] uppercase text-emerald-600 dark:text-emerald-400 font-semibold',
        'text-xs uppercase text-emerald-600 dark:text-emerald-400 font-semibold',
        False,
    ),
    (
        'text-[10px] uppercase text-amber-600 dark:text-amber-400 font-semibold',
        'text-xs uppercase text-amber-600 dark:text-amber-400 font-semibold',
        False,
    ),
    (
        'text-[11px] uppercase tracking-wide text-ink-4 font-semibold',
        'text-xs uppercase tracking-wide text-ink-4 font-semibold',
        False,
    ),
    (
        'text-[11px] leading-snug text-ink-3 mt-0.5',
        'text-sm leading-snug text-ink-3 mt-0.5',
        False,
    ),
    (
        'text-[11px] leading-snug text-amber-700 dark:text-amber-300 flex gap-1.5',
        'text-sm leading-snug text-amber-700 dark:text-amber-300 flex gap-1.5',
        False,
    ),
    (
        'text-[11px] leading-snug text-rose-700 dark:text-rose-300 flex gap-1.5',
        'text-sm leading-snug text-rose-700 dark:text-rose-300 flex gap-1.5',
        False,
    ),
    (
        'text-[11px] text-ink-3 hover:text-ink rounded-md',
        'text-sm text-ink-3 hover:text-ink rounded-md',
        False,
    ),
])

# ═══════════════════════════════════════════════════════════════════
#  Admin.tsx
# ═══════════════════════════════════════════════════════════════════
apply("pages/Admin.tsx", [
    (
        'bg-brand-600 text-white text-sm font-medium rounded-lg hover:bg-brand-700',
        'bg-brand-600 text-brand-900 text-sm font-medium rounded-lg hover:bg-brand-700',
        False,
    ),
    (
        'text-sm text-gray-400',
        'text-sm text-gray-600',
        False,
    ),
    (
        'text-xs text-gray-400 font-mono truncate max-w-[200px]',
        'text-xs text-gray-600 font-mono truncate max-w-[200px]',
        False,
    ),
])

full = os.path.join(SRC, "pages/Admin.tsx")
content = read_file(full)
content = content.replace("text-gray-500", "text-gray-600")
write_file(full, content)

# ═══════════════════════════════════════════════════════════════════
#  Docs.tsx
# ═══════════════════════════════════════════════════════════════════
apply("pages/Docs.tsx", [
    (
        'bg-brand-600 text-white font-semibold grid place-items-center shrink-0',
        'bg-brand-600 text-brand-900 font-semibold grid place-items-center shrink-0',
        False,
    ),
])

# ═══════════════════════════════════════════════════════════════════
#  FreeAssessment.tsx
# ═══════════════════════════════════════════════════════════════════
apply("pages/FreeAssessment.tsx", [
    (
        'bg-brand-600 text-white flex items-center justify-center',
        'bg-brand-600 text-brand-900 flex items-center justify-center',
        False,
    ),
    (
        'bg-gradient-brand text-white p-6 sm:p-8 relative overflow-hidden',
        'bg-gradient-brand text-brand-900 p-6 sm:p-8 relative overflow-hidden',
        False,
    ),
    (
        'text-xs text-gray-400',
        'text-xs text-gray-600',
        False,
    ),
    (
        'text-gray-400 font-normal',
        'text-gray-600 font-normal',
        False,
    ),
])

# ═══════════════════════════════════════════════════════════════════
#  NoCode.tsx
# ═══════════════════════════════════════════════════════════════════
apply("pages/NoCode.tsx", [
    (
        "? 'bg-brand-600 text-white shadow-lg shadow-brand-200'",
        "? 'bg-brand-600 text-brand-900 shadow-lg shadow-brand-200'",
        False,
    ),
    (
        'bg-brand-600 text-white hover:bg-brand-500 shadow-sm shadow-brand-200 transition-all',
        'bg-brand-600 text-brand-900 hover:bg-brand-500 shadow-sm shadow-brand-200 transition-all',
        False,
    ),
    (
        'bg-brand-600 text-white hover:bg-brand-500',
        'bg-brand-600 text-brand-900 hover:bg-brand-500',
        True,
    ),
    (
        'bg-gray-100 text-gray-400',
        'bg-gray-100 text-gray-600',
        False,
    ),
    (
        'text-[10px] text-gray-500',
        'text-xs text-gray-600',
        False,
    ),
])

full = os.path.join(SRC, "pages/NoCode.tsx")
content = read_file(full)
content = content.replace("text-gray-500", "text-gray-600")
write_file(full, content)

# ═══════════════════════════════════════════════════════════════════
#  SDKDocs.tsx
# ═══════════════════════════════════════════════════════════════════
apply("pages/SDKDocs.tsx", [
    (
        'bg-brand-600 text-white rounded-md hover:bg-brand-700 text-sm',
        'bg-brand-600 text-brand-900 rounded-md hover:bg-brand-700 text-sm',
        False,
    ),
    (
        'text-slate-400',
        'text-slate-600',
        True,
    ),
])

full = os.path.join(SRC, "pages/SDKDocs.tsx")
content = read_file(full)
content = content.replace("text-slate-500", "text-slate-600")
write_file(full, content)

# ═══════════════════════════════════════════════════════════════════
#  Setup.tsx
# ═══════════════════════════════════════════════════════════════════
apply("pages/Setup.tsx", [
    (
        "? 'bg-brand-600 text-white shadow-md shadow-brand-200'",
        "? 'bg-brand-600 text-brand-900 shadow-md shadow-brand-200'",
        False,
    ),
    (
        'bg-brand-600 text-white font-semibold text-sm hover:bg-brand-500',
        'bg-brand-600 text-brand-900 font-semibold text-sm hover:bg-brand-500',
        False,
    ),
    (
        'text-xs font-semibold text-gray-400 uppercase tracking-wider',
        'text-xs font-semibold text-gray-600 uppercase tracking-wider',
        True,
    ),
    (
        'text-gray-400 hover:text-white',
        'text-gray-600 hover:text-white',
        False,
    ),
    (
        'text-gray-400',
        'text-gray-600',
        True,
    ),
    (
        'text-[11px]',
        'text-xs',
        False,
    ),
])

full = os.path.join(SRC, "pages/Setup.tsx")
content = read_file(full)
content = content.replace("text-gray-500", "text-gray-600")
write_file(full, content)

# ═══════════════════════════════════════════════════════════════════
#  ReasoningTape.tsx
# ═══════════════════════════════════════════════════════════════════
full = os.path.join(SRC, "components/ReasoningTape.tsx")
content = read_file(full)
content = content.replace("text-slate-400", "text-slate-600")
content = content.replace("text-slate-500", "text-slate-600")
write_file(full, content)

# ═══════════════════════════════════════════════════════════════════
#  ReasoningTimeline.tsx
# ═══════════════════════════════════════════════════════════════════
full = os.path.join(SRC, "components/ReasoningTimeline.tsx")
content = read_file(full)
content = content.replace("text-slate-400", "text-slate-600")
content = content.replace("text-slate-500", "text-slate-600")
write_file(full, content)

# ═══════════════════════════════════════════════════════════════════
#  Other pages with text-gray-400/500 (global safe replacements)
# ═══════════════════════════════════════════════════════════════════
for fname in [
    "pages/ComplianceReport.tsx",
    "pages/DPIA.tsx",
    "pages/EvidencePack.tsx",
    "pages/RiskAssessment.tsx",
    "pages/SessionAudit.tsx",
    "pages/TechnicalDocs.tsx",
    "pages/Transparency.tsx",
    "pages/Sidecar.tsx",
    "pages/Setup.tsx",  # already done but harmless
]:
    full = os.path.join(SRC, fname)
    if not os.path.exists(full):
        continue
    content = read_file(full)
    content = content.replace("text-gray-400", "text-gray-600")
    content = content.replace("text-gray-500", "text-gray-600")
    write_file(full, content)

print("Done applying accessibility fixes.")
