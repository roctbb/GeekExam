<template>
  <FontAwesomeIcon :icon="icons[name]" class="ge-icon" aria-hidden="true" focusable="false" />
</template>

<script>
import { FontAwesomeIcon } from '@fortawesome/vue-fontawesome'
import {
  faArrowDown, faArrowLeft, faArrowRight, faArrowUp, faChartColumn,
  faCheck, faChevronDown, faCircleCheck, faCircleHalfStroke, faCircleXmark, faClipboardList,
  faClock, faEye, faFileArrowUp, faFlagCheckered, faFloppyDisk, faFolderOpen,
  faKey, faMinus, faMoon, faPenToSquare, faPlay, faPlus, faRightFromBracket,
  faRightToBracket, faRotateRight, faStop, faSun, faTrashCan, faTriangleExclamation,
} from '@fortawesome/free-solid-svg-icons'

// Keep the icon set explicit so the rest of Font Awesome is removed from the build.
const icons = {
  'arrow-down': faArrowDown, 'arrow-left': faArrowLeft, 'arrow-right': faArrowRight,
  'arrow-up': faArrowUp, 'chevron-down': faChevronDown, results: faChartColumn, check: faCheck,
  'circle-check': faCircleCheck, 'circle-half-stroke': faCircleHalfStroke,
  'circle-xmark': faCircleXmark, tests: faClipboardList, clock: faClock,
  preview: faEye, upload: faFileArrowUp, finish: faFlagCheckered, save: faFloppyDisk,
  open: faFolderOpen, key: faKey, minus: faMinus, moon: faMoon, edit: faPenToSquare,
  play: faPlay, plus: faPlus, logout: faRightFromBracket, login: faRightToBracket,
  retry: faRotateRight, stop: faStop, sun: faSun, delete: faTrashCan,
  warning: faTriangleExclamation,
}

export default {
  components: { FontAwesomeIcon },
  props: { name: { type: String, required: true, validator: name => Object.hasOwn(icons, name) } },
  setup: () => ({ icons }),
}
</script>
