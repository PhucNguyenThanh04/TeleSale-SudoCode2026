# LangMem Only Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove obsolete memory execution modes while retaining LangMem long term memory and synchronous session history.

**Architecture:** The agent commits masked turns and tool observations, then the worker distills facts and episodes asynchronously into `runtime.store`. The memory MCP reads accepted store revisions. Legacy tables remain solely as historical data for existing migrations and optional backfill; no live agent path reads or writes them.

**Tech Stack:** Python, LangGraph, LangMem, PostgreSQL, MCP.

**Spec:** The user requested that only LangMem remain as the memory implementation, with old modes removed.

## Review Focus

- Same session conversation history remains available immediately after each turn.
- Identified customer facts and episodes come only from completed LangMem revisions.
- Old memory actions cannot write to legacy fact or episode tables.
- A failed store read does not silently return stale legacy knowledge.
- Existing customer rows and migration/backfill utilities are not deleted.

## Task 1: Pin the memory contract to LangMem

- [x] Add focused regression tests for read, commit, action rejection and worker mode.
- [x] Remove `off`/`shadow` configuration and worker branches.
- [x] Simplify memory MCP service and schemas to LangMem-only read and commit.
- [x] Run focused tests.

## Task 2: Remove the legacy agent path

- [x] Add tests proving only the LangMem prompt and business tool schemas are used.
- [x] Remove the legacy fact proposal and extraction branches from agent runtime.
- [x] Preserve current session history and verified order links.
- [x] Run agent tests and adjust obsolete tests.

## Task 3: Verify and document

- [x] Update configuration examples and README.
- [x] Run AI service and backend regression suites and PostgreSQL integration tests.
- [x] Inspect remaining `off`/`shadow` references and report any historical-only artifacts.
