class DockerChecker:
    def submit(self, answer_id, answer_value, check_config, question_body, check_type='docker', max_points=10):
        """Freeze and queue a check through the shared GeekExecutor protocol."""
        from executor_service import submit
        return submit(answer_id, answer_value, check_config, question_body, check_type, max_points)
