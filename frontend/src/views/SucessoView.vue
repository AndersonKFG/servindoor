<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import QRCode from 'qrcode'
import confetti from 'canvas-confetti'

const route = useRoute()
const ingressoId = route.params.ingressoId
const solicitacaoId = route.query.solicitacao_id
const queryToken = (route.query.token || '').toString()

const isAnalise = computed(() => {
  return ingressoId === 'analise' || !!solicitacaoId || route.path.includes('/analise')
})

const loading = ref(true)
const acessoNegado = ref(false)
const qrDataUrl = ref(null)
const ingresso = ref(null)
const usuario = ref(null)
const lote = ref(null)
const cpfFormatado = ref('')
const analiseData = ref(null)

async function gerarQRCode(token) {
  try {
    qrDataUrl.value = await QRCode.toDataURL(token, {
      width: 260,
      margin: 2,
      color: {
        dark: '#0f172a',
        light: '#ffffff'
      }
    })
  } catch (err) {
    // Falha silenciosa
  }
}

async function carregarDados() {
  try {
    loading.value = true
    acessoNegado.value = false
    const tokenParam = queryToken ? `?token=${encodeURIComponent(queryToken)}` : ''

    if (isAnalise.value) {
      // Modo Análise Pendente
      const targetId = solicitacaoId || (ingressoId !== 'analise' ? ingressoId : '')
      if (targetId) {
        const res = await fetch(`/api/sucesso/analise-status/${targetId}${tokenParam}`, {
          headers: { 'Accept': 'application/json' },
          credentials: 'include'
        })
        if (res.ok) {
          const data = await res.json()
          analiseData.value = data
          usuario.value = {
            nome: data.usuario?.nome || 'Servidor Municipal',
            secretaria: {
              nome: data.secretaria_nome || 'Secretaria Municipal'
            },
            setor: data.usuario?.setor || '',
            vinculo: 'Servidor',
            email: data.usuario?.email || '',
            cpf: data.usuario?.cpf_mascarado || ''
          }
          lote.value = {
            nome: data.lote_nome || 'Lote Oficial'
          }
          cpfFormatado.value = data.usuario?.cpf_mascarado || ''
        } else {
          acessoNegado.value = true
        }
      }
    } else {
      // Modo Ingresso Emitido Normal
      const res = await fetch(`/api/sucesso/${ingressoId}${tokenParam}`, {
        headers: { 'Accept': 'application/json' },
        credentials: 'include'
      })

      if (res.ok) {
        const data = await res.json()
        const token = data.qr_code_token || data.ingresso?.qr_code_token

        ingresso.value = {
          id: data.id || data.ingresso?.id || ingressoId,
          qr_code_token: token
        }

        usuario.value = {
          nome: data.usuario?.nome || 'Servidor Municipal',
          secretaria: {
            nome: data.usuario?.secretaria_nome || data.usuario?.secretaria?.nome || 'Prefeitura Municipal'
          },
          setor: data.usuario?.setor || '',
          vinculo: data.usuario?.vinculo || 'Servidor',
          telefone: data.usuario?.telefone || 'Informado',
          cpf: data.usuario?.cpf_formatado || data.cpf || ''
        }

        lote.value = {
          nome: data.lote_nome || data.lote?.nome || 'Lote Oficial'
        }

        cpfFormatado.value = data.usuario?.cpf_formatado || data.cpf || ''

        if (token) {
          await gerarQRCode(token)
        }

        confetti({
          particleCount: 70,
          spread: 60,
          origin: { y: 0.5 }
        })
      } else {
        acessoNegado.value = true
      }
    }
  } catch (e) {
    acessoNegado.value = true
  } finally {
    loading.value = false
  }
}

function handleImprimir() {
  const token = ingresso.value?.qr_code_token || analiseData.value?.ingresso?.qr_code_token
  if (token) {
    window.open(`/api/meu-ingresso/download-pdf/${token}`, '_blank')
  }
}

onMounted(() => {
  carregarDados()
})
</script>


<template>
  <div class="sucesso-page">
    <div class="app-container">
      <div class="sucesso-wrapper">
        <div class="vip-card ticket-card" :class="{ 'ticket-card--analysis': isAnalise }">
          
          <!-- ============================================================= -->
          <!-- CENÁRIO 0: ACESSO NÃO AUTORIZADO (PROTEÇÃO IDOR/LGPD)          -->
          <!-- ============================================================= -->
          <template v-if="acessoNegado">
            <div class="ticket-header text-center py-4">
              <span class="vip-badge ticket-access-restricted-badge mb-3">
                <i class="bi bi-shield-x me-1"></i> Acesso Restrito
              </span>
              <h2 class="servant-name font-outfit">Comprovante Protegido</h2>
              <p class="servant-org mt-2">
                Por motivos de segurança e proteção de dados, este comprovante só pode ser acessado no mesmo navegador de onde foi resgatado ou através do link seguro com chave de acesso.
              </p>
            </div>
            <div class="ticket-actions no-print mt-4">
              <router-link to="/" class="btn-secondary w-100 font-outfit text-center">
                <i class="bi bi-house-door me-1"></i> Voltar à Página Inicial
              </router-link>
            </div>
          </template>

          <!-- ============================================================= -->
          <!-- CENÁRIO 1: SOLICITAÇÃO EM ANÁLISE MANUAL (VALIDADOR)           -->
          <!-- ============================================================= -->
          <template v-else-if="isAnalise">
            <div class="ticket-header analysis-header">
              <span class="vip-badge badge-analise">
                <i class="bi bi-hourglass-split me-1"></i> Cadastro em Análise &bull; Vaga Retida no Lote
              </span>

              <h2 class="servant-name font-outfit">
                {{ usuario?.nome || 'Servidor Municipal' }}
              </h2>
              <p class="servant-org">
                {{ usuario?.secretaria?.nome || 'Secretaria Municipal' }}
                <span v-if="usuario?.setor"> &bull; {{ usuario.setor }}</span>
              </p>
            </div>

            <!-- Card de Destaque da Análise -->
            <div class="analise-status-card">
              <div class="analise-icon-glow">
                <i class="bi bi-person-check-fill"></i>
              </div>
              <div class="analise-protocolo-box">
                <span class="analise-protocolo-label">Protocolo de Validação</span>
                <span class="analise-protocolo-valor font-outfit">
                  #VAL-{{ String(analiseData?.id || solicitacaoId || '001').padStart(5, '0') }}
                </span>
              </div>
              <div class="analise-pill">
                <i class="bi bi-shield-lock me-1"></i>
                Vaga garantida no lote &bull; Prazo: até 72 horas
              </div>
            </div>

            <!-- Detalhes da Solicitação -->
            <div class="ticket-details-box">
              <div class="details-grid analysis-details-grid">
                <div class="detail-item">
                  <span class="detail-label">Lote:</span>
                  <strong class="detail-value">{{ lote?.nome || 'Lote Oficial' }}</strong>
                </div>
                <div class="detail-item">
                  <span class="detail-label">CPF:</span>
                  <strong class="detail-value font-monospace">{{ cpfFormatado || '000.***.***-00' }}</strong>
                </div>
                <div class="detail-item">
                  <span class="detail-label">Secretaria Responsável:</span>
                  <strong class="detail-value">{{ usuario?.secretaria?.nome || 'Secretaria Municipal' }}</strong>
                </div>
                <div class="detail-item">
                  <span class="detail-label">Data da Solicitação:</span>
                  <strong class="detail-value">{{ analiseData?.criado_em || 'Hoje' }}</strong>
                </div>
              </div>
            </div>

            <!-- Box Explicativo com Informações Claras dos 4 Passos -->
            <div class="analise-explanation-alert no-print">
              <div class="alert-icon-wrap">
                <i class="bi bi-info-circle-fill text-warning"></i>
              </div>
              <div class="alert-content-wrap">
                <strong class="alert-title font-outfit">Próximos Passos do seu Resgate</strong>
                <ol class="analysis-steps">
                  <li><strong>Resgate realizado com sucesso:</strong> Seus dados foram recebidos e sua vaga está garantida no lote.</li>
                  <li><strong>Validação:</strong> O sistema e a equipe da <strong>Servindoor</strong> estão validando seu vínculo como servidor(a) municipal.</li>
                  <li><strong>Notificação:</strong> Após a validação, você receberá um e-mail contendo seu <strong>ingresso oficial com QR Code</strong> ou informando eventuais pendências.</li>
                  <li><strong>Prazo:</strong> Todo esse processo de validação ocorrerá em <strong>até 72 horas</strong>.</li>
                </ol>
              </div>
            </div>

            <!-- Ações -->
            <div class="ticket-actions no-print">
              <router-link to="/meu-ingresso" class="btn-primary w-100 font-outfit text-center">
                <i class="bi bi-ticket-detailed me-1"></i> Consultar em "Meu Ingresso"
              </router-link>
              <router-link to="/" class="btn-secondary w-100 font-outfit text-center">
                <i class="bi bi-house-door me-1"></i> Voltar à Página Inicial
              </router-link>
            </div>

            <p class="ticket-notice no-print">
              <i class="bi bi-shield-check text-cyan me-1"></i> Sua vaga não será liberada para outros servidores durante o período de análise.
            </p>
          </template>


          <!-- ============================================================= -->
          <!-- CENÁRIO 2: INGRESSO EMITIDO COM SUCESSO (QR CODE DISPONÍVEL)  -->
          <!-- ============================================================= -->
          <template v-else>
            <div class="ticket-header">
              <span class="vip-badge bg-success mb-3">
                <i class="bi bi-check-circle-fill me-1"></i> Vaga Garantida &bull; Ingresso Emitido
              </span>

              <h2 class="servant-name font-outfit">
                {{ usuario?.nome || 'Servidor Municipal' }}
              </h2>
              <p class="servant-org">
                {{ usuario?.secretaria?.nome || 'Prefeitura Municipal' }}
                <span v-if="usuario?.setor"> &bull; {{ usuario.setor }}</span>
              </p>
            </div>

            <!-- Card do QR Code -->
            <div class="qr-container">
              <img v-if="qrDataUrl" :src="qrDataUrl" alt="QR Code do Ingresso" class="qr-image" />
              <div v-else class="qr-placeholder">
                <i class="bi bi-qr-code"></i>
              </div>

              <div class="token-box">
                <span class="token-label">Token de Acesso Portaria</span>
                <code class="token-code font-outfit">{{ ingresso?.qr_code_token || 'GERANDO TOKEN...' }}</code>
              </div>
            </div>

            <!-- Detalhes do Ingresso -->
            <div class="ticket-details-box">
              <div class="details-grid">
                <div class="detail-item">
                  <span class="detail-label">Lote:</span>
                  <strong class="detail-value">{{ lote?.nome || 'Lote Oficial' }}</strong>
                </div>
                <div class="detail-item">
                  <span class="detail-label">CPF:</span>
                  <strong class="detail-value font-monospace">{{ cpfFormatado || usuario?.cpf || '000.***.***-00' }}</strong>
                </div>
                <div class="detail-item">
                  <span class="detail-label">Vínculo:</span>
                  <strong class="detail-value">{{ usuario?.vinculo || 'Servidor' }}</strong>
                </div>
                <div class="detail-item">
                  <span class="detail-label">Contato:</span>
                  <strong class="detail-value">{{ usuario?.telefone || 'Informado' }}</strong>
                </div>
              </div>
            </div>

            <!-- Aviso de Comprovante e Envio por E-mail -->
            <div class="ticket-email-alert no-print">
              <div class="alert-icon-wrap">
                <i class="bi bi-envelope-check-fill"></i>
              </div>
              <div class="alert-content-wrap">
                <strong class="alert-title font-outfit">Ingresso Emitido &bull; Cópia Enviada por E-mail</strong>
                <p class="alert-text">
                  Você pode baixar ou tirar uma captura de tela (print) do seu ingresso agora mesmo. Enviamos também uma cópia completa contendo o ingresso e algumas informações adicionais para o seu e-mail cadastrado.
                </p>
              </div>
            </div>

            <!-- Ações -->
            <div class="ticket-actions no-print">
              <a
                v-if="ingresso?.qr_code_token"
                :href="'/api/meu-ingresso/download-pdf/' + ingresso.qr_code_token"
                target="_blank"
                class="btn-primary w-100 font-outfit text-center d-flex align-items-center justify-content-center"
              >
                <i class="bi bi-file-earmark-pdf-fill me-2"></i> Baixar Ingresso (PDF)
              </a>
              <button v-else type="button" class="btn-primary w-100 font-outfit" @click="handleImprimir">
                <i class="bi bi-file-earmark-pdf-fill me-2"></i> Baixar Ingresso (PDF)
              </button>

              <a
                v-if="ingresso?.qr_code_token"
                :href="'/api/meu-ingresso/download-imagem/' + ingresso.qr_code_token"
                target="_blank"
                download
                class="btn-secondary w-100 font-outfit text-center d-flex align-items-center justify-content-center"
              >
                <i class="bi bi-download me-2"></i> Baixar Imagem (PNG)
              </a>

              <router-link to="/" class="btn-secondary w-100 font-outfit text-center d-flex align-items-center justify-content-center">
                <i class="bi bi-house-door me-2"></i> Voltar à Página Inicial
              </router-link>
            </div>

            <p class="ticket-notice no-print">
              <i class="bi bi-shield-check text-success me-1"></i> Apresente este QR Code na portaria do evento junto com seu documento oficial.
            </p>
          </template>

        </div>
      </div>
    </div>
  </div>
</template>

