<template>
  <div class="ge-fade-in">
    <div class="ge-page-header">
      <div>
        <h4>Сводка по заданиям</h4>
        <p v-if="results?.title" class="small text-muted mb-0 mt-1">{{ results.title }}</p>
      </div>
      <div class="d-flex gap-2">
        <IconAction icon="retry" label="Обновить" :busy="refreshing" @click="refresh" />
        <RouterLink :to="`/admin/tests/${testId}/results`" class="btn btn-outline-secondary btn-sm"><AppIcon name="arrow-left" />К результатам</RouterLink>
      </div>
    </div>
    <div v-if="error" class="alert alert-danger" role="alert">
      {{ error }} <button class="btn btn-sm btn-outline-danger" :disabled="refreshing" @click="refresh">Повторить</button>
    </div>
    <div v-if="loading" class="text-center py-4" role="status" aria-label="Загружаем сводку"><div class="spinner-border" /></div>
    <TestQuestionReview v-else-if="results" :test-id="testId" :groups="results.question_review" />
  </div>
</template>

<script setup>
import { useRoute } from 'vue-router'
import api from '../../api'
import TestQuestionReview from '../../components/TestQuestionReview.vue'
import { useResultList } from '../../composables/useResultList'

const testId = useRoute().params.id
const { results, loading, refreshing, error, refresh } = useResultList(
  () => api.getQuestionReviewSummary(testId), `test_${testId}`, null,
)
</script>
