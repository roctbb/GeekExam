<template>
  <FontAwesomeIcon
    :icon="icons[name]"
    class="app-icon"
    aria-hidden="true"
    focusable="false"
  />
</template>

<script setup>
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import {
  faDoorOpen,
  faWifi,
  faLaptop,
  faPrint,
  faEllipsis,
  faMagnifyingGlass,
  faRotateRight,
  faPlus,
  faXmark,
  faMoon,
  faSun,
  faRightFromBracket,
  faRightToBracket,
  faLock,
  faUnlock,
} from "@fortawesome/free-solid-svg-icons";

defineProps({ name: { type: String, required: true } });
const icons = {
  room: faDoorOpen,
  router: faWifi,
  laptop: faLaptop,
  printer: faPrint,
  more: faEllipsis,
  search: faMagnifyingGlass,
  refresh: faRotateRight,
  plus: faPlus,
  close: faXmark,
  moon: faMoon,
  sun: faSun,
  logout: faRightFromBracket,
  login: faRightToBracket,
  lock: faLock,
  unlock: faUnlock,
};
</script>
