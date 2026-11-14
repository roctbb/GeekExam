import { ref, onMounted, onUnmounted } from 'vue'
import {io} from 'socket.io-client'

export function useResultList(fetchList, room) {
  const attempts=ref([]),loading=ref(true),refreshing=ref(false),error=ref('')
  const socket=io({path:'/socket.io',transports:['websocket'],autoConnect:false})
  let stopped=false,queued=false
  async function refresh() {
    if(stopped)return
    if(refreshing.value){queued=true;return}
    refreshing.value=true
    do {
      queued=false
      try {const {data}=await fetchList();if(!stopped && !queued){attempts.value=data;error.value=''}}
      catch {if(!stopped)error.value='Не удалось обновить результаты. Проверьте соединение и повторите.'}
    } while(!stopped && queued)
    loading.value=false;refreshing.value=false
  }
  function connect(){socket.emit('join',{room},()=>refresh());refresh()}
  function visible(){if(!document.hidden)refresh()}
  onMounted(()=>{
    socket.on('connect',connect);socket.on('attempt_list_updated',refresh);socket.connect()
    document.addEventListener('visibilitychange',visible);window.addEventListener('online',refresh);refresh()
  })
  onUnmounted(()=>{stopped=true;socket.off('connect',connect);socket.off('attempt_list_updated',refresh);socket.disconnect();document.removeEventListener('visibilitychange',visible);window.removeEventListener('online',refresh)})
  return {attempts,loading,refreshing,error,refresh}
}
