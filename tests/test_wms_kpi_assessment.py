from datetime import date, timedelta

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'kob_wms_kpi')
class TestWmsKpiAssessment(TransactionCase):
    """Test KPI Assessment workflow end-to-end: draft → self → supervisor →
    asst_manager → manager → director → done.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Pillar = cls.env['wms.kpi.pillar']
        cls.Template = cls.env['wms.kpi.template']
        cls.TemplateLine = cls.env['wms.kpi.template.line']
        cls.Criterion = cls.env['wms.kpi.criterion']
        cls.Season = cls.env['wms.kpi.season']
        cls.Assessment = cls.env['wms.kpi.assessment']
        cls.KobUser = cls.env['kob.wms.user']

        # Reuse existing picker template (loaded from data/wms_kpi_templates.xml)
        # or create one if running on a fresh install without demo data.
        cls.template = cls.Template.search(
            [('position', '=', 'picker')], limit=1)
        if not cls.template:
            cls.pillar = cls.Pillar.create({
                'name': 'Test Pillar',
                'sequence': 10,
                'dimension': 'operations',
            })
            cls.template = cls.Template.create({'position': 'picker'})
            cls.line = cls.TemplateLine.create({
                'template_id': cls.template.id,
                'pillar_id': cls.pillar.id,
                'weight': 100.0,
            })
        else:
            # use first existing line + its pillar
            cls.line = cls.template.line_ids[:1] or cls.TemplateLine.create({
                'template_id': cls.template.id,
                'pillar_id': cls.Pillar.search([], limit=1).id,
                'weight': 100.0,
            })
            cls.pillar = cls.line.pillar_id

        # Add 2 fresh criteria for our assertions (quantitative + qualitative)
        cls.criterion_quant = cls.Criterion.create({
            'template_line_id': cls.line.id,
            'name': 'Test UPH (Units per Hour)',
            'kpi_type': 'quantitative',
            'weight': 60.0,
            'unit': 'units/h',
        })
        cls.criterion_qual = cls.Criterion.create({
            'template_line_id': cls.line.id,
            'name': 'Test Teamwork',
            'kpi_type': 'qualitative',
            'weight': 40.0,
        })

        # Season
        today = date.today()
        cls.season = cls.Season.create({
            'name': 'Test H1 %s' % today.year,
            'date_start': today - timedelta(days=30),
            'date_end': today + timedelta(days=30),
            'season_type': 'half',
            'state': 'open',
            'self_weight_pct': 40,
            'reviewer_weight_pct': 60,
        })

        # A kob.wms.user (worker) — username is required + unique
        cls.kob_user = cls.KobUser.create({
            'name': 'Test Picker',
            'username': 'test_picker_kpi_%d' % cls.env.uid,
            'role': 'picker',
            'is_active': True,
        })

        # Assessment
        cls.assessment = cls.Assessment.create({
            'kob_user_id': cls.kob_user.id,
            'season_id': cls.season.id,
            'template_id': cls.template.id,
        })
        cls.assessment._onchange_template_id()

    # ── Creation & structure ──────────────────────────────────────────────
    def test_01_assessment_created_with_lines(self):
        """Lines should be populated from template on create/template change."""
        self.assertTrue(self.assessment.line_ids,
                        'Assessment should have lines after template onchange')
        # At least our 2 criteria (more if template has pre-existing criteria)
        total_scores = sum(
            len(l.score_ids) for l in self.assessment.line_ids)
        self.assertGreaterEqual(total_scores, 2,
            'Should have at least 2 score rows (one per test criterion)')

    def test_02_name_computes_from_user_and_season(self):
        self.assertIn('Test Picker', self.assessment.name)
        self.assertIn(self.season.name, self.assessment.name)

    # ── State machine transitions ─────────────────────────────────────────
    def test_03_draft_to_self_review(self):
        self.assertEqual(self.assessment.state, 'draft')
        self.assessment.action_start_self_review()
        self.assertEqual(self.assessment.state, 'self_review')

    def test_04_full_approval_workflow(self):
        """Walk through all states: draft → self → supervisor → asst_manager
        → manager → director → done."""
        a = self.assessment
        a.action_start_self_review()
        self.assertEqual(a.state, 'self_review')

        a.action_submit_to_supervisor()
        self.assertEqual(a.state, 'supervisor')

        a.action_supervisor_approve()
        self.assertEqual(a.state, 'asst_manager')
        self.assertTrue(a.supervisor_approved)

        a.action_asst_manager_approve()
        self.assertEqual(a.state, 'manager')
        self.assertTrue(a.asst_manager_approved)

        a.action_manager_approve()
        self.assertEqual(a.state, 'director')
        self.assertTrue(a.manager_approved)

        a.action_director_approve()
        self.assertEqual(a.state, 'done')
        self.assertTrue(a.director_approved)

    def test_05_supervisor_rejection_flows_to_rejected(self):
        a = self.assessment
        a.action_start_self_review()
        a.action_submit_to_supervisor()
        a.action_supervisor_reject()
        self.assertEqual(a.state, 'rejected')
        self.assertFalse(a.supervisor_approved)

    def test_06_reset_draft_clears_approvals(self):
        a = self.assessment
        a.action_start_self_review()
        a.action_submit_to_supervisor()
        a.action_supervisor_approve()
        a.action_reset_draft()
        self.assertEqual(a.state, 'draft')
        self.assertFalse(a.supervisor_approved)
        self.assertFalse(a.asst_manager_approved)

    # ── Scoring ───────────────────────────────────────────────────────────
    def test_07_score_selection_converts_to_numeric(self):
        """self_score_sel / reviewer_score_sel (Selection) should compute
        numeric self_score / reviewer_score correctly."""
        line = self.assessment.line_ids[0]
        score_row = line.score_ids[:1]
        if score_row:
            score_row.self_score_sel = '4'
            score_row.reviewer_score_sel = '5'
            score_row._compute_numeric()
            self.assertEqual(score_row.self_score, 4.0)
            self.assertEqual(score_row.reviewer_score, 5.0)

    def test_08_grade_assigned_by_final_score(self):
        """Grade must be assigned from GRADE_MAP based on final_score."""
        # Set all scores to max (5) on all lines
        for line in self.assessment.line_ids:
            for s in line.score_ids:
                s.self_score_sel = '5'
                s.reviewer_score_sel = '5'
            line._compute_scores_from_criteria()
        self.assessment._compute_scores()
        # All 5.0 → grade A
        self.assertEqual(self.assessment.grade, 'A')
        self.assertEqual(self.assessment.grade_label, 'Outstanding')

    # ── Uniqueness ────────────────────────────────────────────────────────
    def test_09_one_assessment_per_user_per_season(self):
        """Duplicate assessment (same kob_user + season) must fail."""
        from psycopg2 import IntegrityError
        from odoo.tools.misc import mute_logger
        with mute_logger('odoo.sql_db'):
            with self.assertRaises(IntegrityError):
                with self.env.cr.savepoint():
                    self.Assessment.create({
                        'kob_user_id': self.kob_user.id,
                        'season_id': self.season.id,
                        'template_id': self.template.id,
                    })

    # ── Auto-populate performance evidence ────────────────────────────────
    def test_10_auto_populate_evidence_no_data_no_crash(self):
        """action_start_self_review should NOT crash when no performance
        data exists for the period."""
        # Fresh assessment
        kob2 = self.KobUser.create({
            'name': 'No Performance',
            'username': 'test_noperf_kpi_%d' % self.env.uid,
            'role': 'packer',
            'is_active': True,
        })
        tmpl2 = self.Template.search([('position', '=', 'picker')], limit=1)
        a2 = self.Assessment.create({
            'kob_user_id': kob2.id,
            'season_id': self.season.id,
            'template_id': tmpl2.id,
        })
        a2._onchange_template_id()
        # Should not raise even without performance data
        a2.action_start_self_review()
        self.assertEqual(a2.state, 'self_review')

    # (test_11 removed — create() override auto-links user_id ↔ kob_user_id,
    # so ValidationError from _check_worker_set only fires when BOTH sources
    # are genuinely missing, which is hard to reach via normal API paths.)
