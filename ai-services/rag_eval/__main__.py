import argparse
import asyncio
import sys
from pathlib import Path

from rag_eval.dataset import DEFAULT_ASSERTIONS, DEFAULT_CONTEXTS, write_json


def parser():
    result = argparse.ArgumentParser(description='Independent RAG eval: retrieval, generation and offline replay')
    commands = result.add_subparsers(dest='command', required=True)
    run = commands.add_parser('run', help='Live MCP retrieval and optional isolated generation')
    run.add_argument('--btc-root', type=Path, required=True)
    run.add_argument('--out', type=Path, required=True)
    run.add_argument('--mode', choices=['retrieval', 'end-to-end'], default='retrieval')
    run.add_argument('--contexts', type=Path, default=DEFAULT_CONTEXTS)
    run.add_argument('--assertions', type=Path, default=DEFAULT_ASSERTIONS)
    run.add_argument('--top-k', type=int, default=5)
    run.add_argument('--include-supplements', action='store_true')
    run.add_argument('--allow-live', action='store_true', help='Explicitly authorize embedding/model calls')
    score = commands.add_parser('score', help='Offline replay; no network or AI settings needed')
    score.add_argument('--run', type=Path, required=True)
    score.add_argument('--out', type=Path, required=True)
    score.add_argument('--judgments', type=Path, help='Completed judge directory bound to this trace')
    score.add_argument('--human-labels', type=Path)
    judge = commands.add_parser('judge', help='Paid Ragas/business judging of saved generation outputs')
    judge.add_argument('--run', type=Path, required=True)
    judge.add_argument('--out', type=Path, required=True)
    judge.add_argument('--allow-live', action='store_true')
    comparison = commands.add_parser('compare', help='Compare two compatible scored directories offline')
    comparison.add_argument('--before', type=Path, required=True)
    comparison.add_argument('--after', type=Path, required=True)
    comparison.add_argument('--out', type=Path, required=True)
    return result


async def live_run(args):
    from rag_eval.adapters import Generator, MCPRetriever, RetrievalSettings
    from rag_eval.runner import collect, read_trace
    retriever = MCPRetriever(RetrievalSettings(), include_supplements=args.include_supplements)
    generator = None
    if args.mode == 'end-to-end':
        from app.configs import get_settings
        generator = Generator(get_settings())
    await collect(args.btc_root, args.out, retriever, generator, top_k=args.top_k,
                  context_path=args.contexts, assertions_path=args.assertions)
    return int(any(row['status'] != 'ok' for row in read_trace(args.out)))


async def live_judge(args):
    from rag_eval.judging import JudgeSettings, RagasJudge, judge_run
    from rag_eval.scoring import validated_run
    validated_run(args.run)
    judge = RagasJudge(JudgeSettings())
    try:
        report = await judge_run(args.run, args.out, judge)
    finally:
        await judge.close()
    return int(any((row.get('judgment') or {}).get('errors') for row in report['cases']))


def main(argv=None):
    cli = parser()
    args = cli.parse_args(argv)
    if args.command in {'run', 'judge'} and not args.allow_live:
        cli.error('Live work requires --allow-live; retrieval may call paid embeddings, judge calls models')
    if args.out.exists():
        cli.error('Output exists; choose a new directory (artifacts are never overwritten)')
    try:
        if args.command == 'run':
            return asyncio.run(live_run(args))
        if args.command == 'judge':
            return asyncio.run(live_judge(args))
        if args.command == 'score':
            from rag_eval.scoring import score_run
            judgments, identity = None, None
            if args.judgments:
                from rag_eval.runner import separate_output
                separate_output(args.out, args.judgments)
                from rag_eval.judging import load_judgments
                judgments, identity = load_judgments(args.judgments, args.run)
            if args.human_labels and not args.judgments:
                cli.error('--human-labels requires --judgments for independent judge calibration')
            score_run(args.run, args.out, judgments=judgments, judge_identity=identity,
                      human_labels=args.human_labels)
        else:
            from rag_eval.runner import seal, separate_output
            from rag_eval.scoring import compare
            result = compare(args.before, args.after)
            separate_output(args.out, args.before, args.after)
            args.out.mkdir(parents=True, exist_ok=False)
            write_json(args.out / 'comparison.json', result)
            seal(args.out, {'schema_version': 1, 'kind': 'comparison', 'status': 'complete'})
        print(str(args.out), flush=True)
        return 0
    except KeyboardInterrupt:
        print('Interrupted; completed rows retained. Inspect manifest and trace before a new run.', file=sys.stderr)
        return 130
    except Exception as exc:
        print(f'RAG eval failed ({type(exc).__name__}); check paths, credentials, pinned dependencies and artifact integrity. '
              'See retained manifest/trace if output was created.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
