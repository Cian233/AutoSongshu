from __future__ import annotations

import unittest

from autosongshu_agent.memory.compaction import (
    MessageImportanceScorer,
    SemanticChunker,
    Chunk,
    score_message_importance,
    MessageImportance,
    select_messages_for_compaction,
)
from autosongshu_agent.memory.context_window import TokenCounter
from autosongshu_agent.memory.orchestrator import (
    RealTimeMemoryUpdater,
    ExtractedFinding,
)


class MessageImportanceScorerTests(unittest.TestCase):
    def test_scorer_default_initialization(self) -> None:
        scorer = MessageImportanceScorer()
        self.assertEqual(scorer.time_decay_rate, 0.05)
        self.assertIn("system", scorer.role_weights)
        self.assertIn("user", scorer.role_weights)
        self.assertIn("assistant", scorer.role_weights)
        self.assertEqual(scorer.content_value_weight, 0.3)
        self.assertEqual(scorer.structural_weight, 0.2)
        self.assertEqual(scorer.time_decay_weight, 0.3)

    def test_score_system_message(self) -> None:
        scorer = MessageImportanceScorer()
        msg = {"index": 0, "role": "system", "content": "You are a helpful assistant."}
        score = scorer.score(msg, total_messages=5)
        self.assertGreater(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_score_user_message(self) -> None:
        scorer = MessageImportanceScorer()
        msg = {"index": 1, "role": "user", "content": "Scan the target for vulnerabilities."}
        score = scorer.score(msg, total_messages=5)
        self.assertGreater(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_score_assistant_message(self) -> None:
        scorer = MessageImportanceScorer()
        msg = {"index": 2, "role": "assistant", "content": "I found 3 open ports."}
        score = scorer.score(msg, total_messages=5)
        self.assertGreater(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_score_message_with_findings(self) -> None:
        scorer = MessageImportanceScorer()
        msg = {
            "index": 3,
            "role": "assistant",
            "content": "I found a SQL injection vulnerability in the login form. The finding has been confirmed and validated.",
        }
        score = scorer.score(msg, total_messages=5)
        finding_score = scorer.score(
            {"index": 3, "role": "assistant", "content": "Just a normal message."},
            total_messages=5,
        )
        self.assertGreater(score, finding_score)

    def test_score_message_with_code(self) -> None:
        scorer = MessageImportanceScorer()
        msg = {
            "index": 2,
            "role": "assistant",
            "content": "```python\ndef exploit():\n    return True\n```",
        }
        score = scorer.score(msg, total_messages=5)
        self.assertGreater(score, 0.0)

    def test_score_message_with_structural_keywords(self) -> None:
        scorer = MessageImportanceScorer()
        msg = {
            "index": 2,
            "role": "assistant",
            "content": "## Summary: The key finding is an XSS vulnerability. Decision: proceed with exploitation.",
        }
        score = scorer.score(msg, total_messages=5)
        self.assertGreater(score, 0.0)

    def test_score_message_with_summary_tag(self) -> None:
        scorer = MessageImportanceScorer()
        msg = {
            "index": 2,
            "role": "assistant",
            "content": "<summary>Compacted messages summary</summary>",
        }
        score = scorer.score(msg, total_messages=5)
        self.assertGreater(score, 0.0)

    def test_score_empty_content(self) -> None:
        scorer = MessageImportanceScorer()
        msg = {"index": 0, "role": "user", "content": ""}
        score = scorer.score(msg, total_messages=1)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_score_single_message(self) -> None:
        scorer = MessageImportanceScorer()
        msg = {"index": 0, "role": "user", "content": "Hello"}
        score = scorer.score(msg, total_messages=1)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_score_recent_message_gets_higher_score(self) -> None:
        scorer = MessageImportanceScorer()
        old_msg = {"index": 0, "role": "user", "content": "Old message"}
        new_msg = {"index": 9, "role": "user", "content": "New message"}
        old_score = scorer.score(old_msg, total_messages=10)
        new_score = scorer.score(new_msg, total_messages=10)
        self.assertGreater(new_score, old_score)

    def test_score_clamped_to_valid_range(self) -> None:
        scorer = MessageImportanceScorer()
        for i in range(20):
            msg = {"index": i, "role": "assistant", "content": f"Message {i}"}
            score = scorer.score(msg, total_messages=20)
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 1.0)

    def test_custom_role_weights(self) -> None:
        scorer = MessageImportanceScorer(
            role_weights={"system": 0.5, "user": 0.3, "assistant": 0.2, "tool": 0.1}
        )
        msg = {"index": 0, "role": "system", "content": "System message"}
        score = scorer.score(msg, total_messages=1)
        self.assertGreaterEqual(score, 0.0)


class ScoreMessageImportanceFunctionTests(unittest.TestCase):
    def test_score_message_importance_returns_message_importance(self) -> None:
        msg = {"index": 0, "role": "user", "content": "Test message", "turn_number": 1}
        result = score_message_importance(msg, total_messages=5, current_turn=3)
        self.assertIsInstance(result, MessageImportance)
        self.assertEqual(result.message_index, 0)
        self.assertEqual(result.role, "user")

    def test_score_message_with_finding_keywords(self) -> None:
        msg = {
            "index": 2,
            "role": "assistant",
            "content": "Found a vulnerability: SQL injection confirmed and validated.",
            "turn_number": 2,
        }
        result = score_message_importance(msg, total_messages=5, current_turn=3)
        self.assertTrue(result.has_findings)

    def test_score_message_with_tool_calls(self) -> None:
        msg = {
            "index": 2,
            "role": "assistant",
            "content": "Executed tool_call and got tool_result",
            "turn_number": 2,
        }
        result = score_message_importance(msg, total_messages=5, current_turn=3)
        self.assertTrue(result.has_tool_calls)

    def test_score_recent_message_flag(self) -> None:
        msg = {"index": 9, "role": "user", "content": "Recent message", "turn_number": 5}
        result = score_message_importance(msg, total_messages=10, current_turn=5)
        self.assertTrue(result.is_recent)

    def test_score_system_message_flag(self) -> None:
        msg = {"index": 0, "role": "system", "content": "System prompt", "turn_number": 0}
        result = score_message_importance(msg, total_messages=5, current_turn=3)
        self.assertTrue(result.is_system)

    def test_score_current_turn_bonus(self) -> None:
        msg = {"index": 4, "role": "assistant", "content": "Current turn message", "turn_number": 3}
        result = score_message_importance(msg, total_messages=5, current_turn=3)
        self.assertGreater(result.score, 0.0)


class SelectMessagesForCompactionTests(unittest.TestCase):
    def test_returns_all_when_under_keep_count(self) -> None:
        messages = [
            {"index": 0, "role": "user", "content": "msg1", "turn_number": 1},
            {"index": 1, "role": "assistant", "content": "msg2", "turn_number": 1},
        ]
        keep, compact = select_messages_for_compaction(messages, keep_count=6)
        self.assertEqual(len(keep), 2)
        self.assertEqual(len(compact), 0)

    def test_splits_messages_by_threshold(self) -> None:
        messages = [
            {"index": i, "role": "user", "content": f"Message {i}", "turn_number": i + 1}
            for i in range(10)
        ]
        keep, compact = select_messages_for_compaction(messages, keep_count=3, importance_threshold=0.6)
        self.assertEqual(len(keep) + len(compact), 10)
        self.assertGreater(len(keep), 0)

    def test_keep_includes_recent_messages(self) -> None:
        messages = [
            {"index": i, "role": "user", "content": f"Message {i}", "turn_number": i + 1}
            for i in range(10)
        ]
        keep, compact = select_messages_for_compaction(messages, keep_count=3)
        keep_indices = [m["index"] for m in keep]
        self.assertIn(9, keep_indices)
        self.assertIn(8, keep_indices)
        self.assertIn(7, keep_indices)

    def test_results_sorted_by_index(self) -> None:
        messages = [
            {"index": i, "role": "user", "content": f"Message {i}", "turn_number": i + 1}
            for i in range(8)
        ]
        keep, compact = select_messages_for_compaction(messages, keep_count=2)
        keep_indices = [m["index"] for m in keep]
        self.assertEqual(keep_indices, sorted(keep_indices))
        compact_indices = [m["index"] for m in compact]
        self.assertEqual(compact_indices, sorted(compact_indices))


class SemanticChunkerTests(unittest.TestCase):
    def test_chunker_default_config(self) -> None:
        chunker = SemanticChunker()
        self.assertEqual(chunker.max_chunk_tokens, 4000)
        self.assertEqual(chunker.min_chunk_size, 2)
        self.assertEqual(chunker.max_chunk_size, 20)

    def test_chunk_empty_messages(self) -> None:
        chunker = SemanticChunker()
        result = chunker.chunk([])
        self.assertEqual(result, [])

    def test_chunk_single_message(self) -> None:
        chunker = SemanticChunker()
        messages = [{"role": "user", "content": "Hello world"}]
        result = chunker.chunk(messages)
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], Chunk)

    def test_chunk_classifies_high_entropy(self) -> None:
        chunker = SemanticChunker()
        messages = [
            {"role": "assistant", "content": "Found a vulnerability: SQL injection in login form. Exploit confirmed."},
        ]
        result = chunker.chunk(messages)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].chunk_type, "high_value")

    def test_chunk_classifies_low_entropy(self) -> None:
        chunker = SemanticChunker()
        messages = [
            {"role": "user", "content": "ok thanks"},
            {"role": "assistant", "content": "sure, I will help you"},
        ]
        result = chunker.chunk(messages)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].chunk_type, "low_value")

    def test_chunk_produces_summary_for_low_value(self) -> None:
        chunker = SemanticChunker()
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "ok sure"},
            {"role": "user", "content": "thanks"},
        ]
        result = chunker.chunk(messages)
        self.assertTrue(len(result) > 0)
        low_value_chunks = [c for c in result if c.chunk_type == "low_value"]
        if low_value_chunks:
            self.assertTrue(len(low_value_chunks[0].summary) > 0)

    def test_chunk_produces_summary_for_high_value(self) -> None:
        chunker = SemanticChunker()
        messages = [
            {"role": "assistant", "content": "Found SQL injection vulnerability at https://example.test/login. The exploit was successful and confirmed."},
        ]
        result = chunker.chunk(messages)
        high_value_chunks = [c for c in result if c.chunk_type == "high_value"]
        if high_value_chunks:
            self.assertTrue(len(high_value_chunks[0].summary) > 0)

    def test_chunk_respects_max_chunk_size(self) -> None:
        chunker = SemanticChunker(max_chunk_size=3)
        messages = [
            {"role": "user", "content": f"Message {i} about general topic"}
            for i in range(10)
        ]
        result = chunker.chunk(messages)
        for chunk in result:
            self.assertLessEqual(len(chunk.messages), 3)

    def test_chunk_with_budget_constraint(self) -> None:
        chunker = SemanticChunker()
        messages = [
            {"role": "user", "content": f"Message {i} with some content about testing"}
            for i in range(20)
        ]
        result = chunker.chunk(messages, budget=500)
        self.assertIsInstance(result, list)

    def test_chunk_to_dict(self) -> None:
        chunker = SemanticChunker()
        messages = [{"role": "user", "content": "Test"}]
        result = chunker.chunk(messages)
        d = result[0].to_dict()
        self.assertIn("messages", d)
        self.assertIn("chunk_type", d)
        self.assertIn("importance", d)
        self.assertIn("summary", d)
        self.assertIn("token_estimate", d)

    def test_calculate_entropy_empty(self) -> None:
        chunker = SemanticChunker()
        self.assertEqual(chunker._calculate_entropy(""), 0.0)

    def test_calculate_entropy_with_code(self) -> None:
        chunker = SemanticChunker()
        entropy = chunker._calculate_entropy("```python\ndef foo(): pass\n```")
        self.assertGreater(entropy, 0.0)

    def test_classify_message_empty(self) -> None:
        chunker = SemanticChunker()
        self.assertEqual(chunker._classify_message(""), "general")

    def test_is_semantic_boundary(self) -> None:
        chunker = SemanticChunker()
        self.assertTrue(chunker._is_semantic_boundary("new task: scan the target"))
        self.assertFalse(chunker._is_semantic_boundary("just a regular message"))

    def test_compress_low_entropy(self) -> None:
        chunker = SemanticChunker()
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        summary = chunker._compress_low_entropy(messages)
        self.assertIn("compressed", summary)
        self.assertIn("user", summary)
        self.assertIn("assistant", summary)


class TokenCounterTests(unittest.TestCase):
    def test_counter_initialization(self) -> None:
        counter = TokenCounter(model_name="gpt-4")
        self.assertEqual(counter.model_name, "gpt-4")
        self.assertEqual(counter.cache_size, 0)

    def test_count_empty_text(self) -> None:
        counter = TokenCounter()
        self.assertEqual(counter.count(""), 0)

    def test_count_returns_positive_int(self) -> None:
        counter = TokenCounter()
        count = counter.count("Hello, this is a test message with some content.")
        self.assertIsInstance(count, int)
        self.assertGreater(count, 0)

    def test_count_caches_results(self) -> None:
        counter = TokenCounter()
        text = "This is a test message for caching."
        count1 = counter.count(text)
        count2 = counter.count(text)
        self.assertEqual(count1, count2)
        self.assertGreater(counter.cache_size, 0)

    def test_count_messages(self) -> None:
        counter = TokenCounter()
        messages = [
            {"content": "Hello"},
            {"content": "World"},
        ]
        total = counter.count_messages(messages)
        self.assertGreater(total, 0)

    def test_count_messages_with_list_content(self) -> None:
        counter = TokenCounter()
        messages = [
            {"content": [{"type": "text", "text": "Part 1"}, {"type": "text", "text": "Part 2"}]},
        ]
        total = counter.count_messages(messages)
        self.assertGreater(total, 0)

    def test_clear_cache(self) -> None:
        counter = TokenCounter()
        counter.count("Test message one")
        counter.count("Test message two")
        self.assertGreater(counter.cache_size, 0)
        counter.clear_cache()
        self.assertEqual(counter.cache_size, 0)

    def test_count_with_cjk_text(self) -> None:
        counter = TokenCounter()
        cjk_text = "这是一个中文测试文本，用于测试CJK字符的token计数。" * 10
        count = counter.count(cjk_text)
        self.assertGreater(count, 0)

    def test_estimate_cjk_ratio_english(self) -> None:
        counter = TokenCounter()
        ratio = counter._estimate_cjk_ratio("This is pure English text.")
        self.assertEqual(ratio, 0.0)

    def test_estimate_cjk_ratio_mixed(self) -> None:
        counter = TokenCounter()
        ratio = counter._estimate_cjk_ratio("Hello 世界 test 测试")
        self.assertGreater(ratio, 0.0)


class RealTimeMemoryUpdaterTests(unittest.TestCase):
    def test_updater_default_config(self) -> None:
        updater = RealTimeMemoryUpdater()
        self.assertEqual(updater.max_findings_per_tool, 5)
        self.assertEqual(updater.compaction_trigger_threshold, 3)

    def test_process_empty_result(self) -> None:
        updater = RealTimeMemoryUpdater()
        findings = updater.process_tool_result("test_tool", "")
        self.assertEqual(findings, [])

    def test_process_short_result(self) -> None:
        updater = RealTimeMemoryUpdater()
        findings = updater.process_tool_result("test_tool", "short")
        self.assertEqual(findings, [])

    def test_process_vulnerability_finding(self) -> None:
        updater = RealTimeMemoryUpdater()
        result = "Scan complete. vulnerability found: SQL injection detected in /login endpoint."
        findings = updater.process_tool_result("nmap_scan", result)
        self.assertGreater(len(findings), 0)
        vuln_findings = [f for f in findings if f.finding_type == "vulnerability"]
        self.assertGreater(len(vuln_findings), 0)
        self.assertGreater(vuln_findings[0].confidence, 0.0)

    def test_process_credential_finding(self) -> None:
        updater = RealTimeMemoryUpdater()
        result = "Config dump: password=admin123 and token=abcdef1234567890 found in credentials file."
        findings = updater.process_tool_result("config_scan", result)
        cred_findings = [f for f in findings if f.finding_type == "credential"]
        self.assertGreater(len(cred_findings), 0)

    def test_process_network_finding(self) -> None:
        updater = RealTimeMemoryUpdater()
        result = "Port scan results: open port 80, open port 443, service running on 192.168.1.1:8080"
        findings = updater.process_tool_result("port_scan", result)
        net_findings = [f for f in findings if f.finding_type == "network"]
        self.assertGreater(len(net_findings), 0)

    def test_process_error_finding(self) -> None:
        updater = RealTimeMemoryUpdater()
        result = "Application error: Traceback (most recent call last): ConnectionError: failed to connect"
        findings = updater.process_tool_result("http_check", result)
        error_findings = [f for f in findings if f.finding_type == "error"]
        self.assertGreater(len(error_findings), 0)

    def test_finding_source_tool(self) -> None:
        updater = RealTimeMemoryUpdater()
        result = "vulnerability found: XSS detected"
        findings = updater.process_tool_result("my_scanner", result)
        self.assertTrue(all(f.source_tool == "my_scanner" for f in findings))

    def test_max_findings_per_tool(self) -> None:
        updater = RealTimeMemoryUpdater(max_findings_per_tool=2)
        result = "vulnerability found: SQL injection. vulnerability found: XSS. vulnerability found: SSRF. vulnerability found: RCE."
        findings = updater.process_tool_result("scanner", result)
        self.assertLessEqual(len(findings), 2)

    def test_should_trigger_compaction_initial(self) -> None:
        updater = RealTimeMemoryUpdater(compaction_trigger_threshold=3)
        self.assertFalse(updater.should_trigger_compaction())

    def test_should_trigger_compaction_after_threshold(self) -> None:
        updater = RealTimeMemoryUpdater(compaction_trigger_threshold=2)
        updater._findings_count = 5
        updater._last_compaction_trigger = 0
        self.assertTrue(updater.should_trigger_compaction())

    def test_should_not_trigger_when_below_threshold(self) -> None:
        updater = RealTimeMemoryUpdater(compaction_trigger_threshold=5)
        updater._findings_count = 3
        updater._last_compaction_trigger = 0
        self.assertFalse(updater.should_trigger_compaction())

    def test_calculate_confidence_vulnerability(self) -> None:
        updater = RealTimeMemoryUpdater()
        confidence = updater._calculate_confidence(
            "vulnerability", "confirmed SQL injection", "confirmed SQL injection in login form"
        )
        self.assertGreater(confidence, 0.5)

    def test_calculate_confidence_credential(self) -> None:
        updater = RealTimeMemoryUpdater()
        confidence = updater._calculate_confidence(
            "credential", "password=secret123", "password=secret123 found in config"
        )
        self.assertGreater(confidence, 0.5)

    def test_calculate_confidence_clamped_to_range(self) -> None:
        updater = RealTimeMemoryUpdater()
        confidence = updater._calculate_confidence(
            "vulnerability", "confirmed validated 成功 检测到", "very long context " * 20
        )
        self.assertGreaterEqual(confidence, 0.0)
        self.assertLessEqual(confidence, 1.0)

    def test_extracted_finding_dataclass(self) -> None:
        finding = ExtractedFinding(
            content="Test finding",
            finding_type="vulnerability",
            confidence=0.8,
            source_tool="test_tool",
        )
        self.assertEqual(finding.content, "Test finding")
        self.assertEqual(finding.finding_type, "vulnerability")
        self.assertEqual(finding.confidence, 0.8)
        self.assertEqual(finding.source_tool, "test_tool")


if __name__ == "__main__":
    unittest.main()
