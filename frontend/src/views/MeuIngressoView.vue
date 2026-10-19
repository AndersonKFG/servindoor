<script setup>
import { useToast } from '../composables/useToast'
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import QRCode from 'qrcode'
import WebcamCapture from '../components/WebcamCapture.vue'

const { toast } = useToast()

const router = useRouter()

// Etapas: 'consulta', 'ticket', 'validacao_pendente', 'validacao_rejeitada', 'ingresso_cancelado', 'cancel_2fa', 'cancel_selfie', 'cancel_concluido'
const etapaAtual = ref('consulta')

// Campos da Consulta
const cpf = ref('')
const dataNascimento = ref('')
const nascimentoDia = ref('')
const nascimentoMes = ref('')
const nascimentoAno = ref('')
const anoAtual = new Date().getFullYear()
const anosNascimento = computed(() => Array.from(
  { length: anoAtual - 1930 + 1 },
  (_, index) => String(anoAtual - index)
))
const mesesNascimento = [
  { valor: '01', nome: 'Janeiro' }, { valor: '02', nome: 'Fevereiro' },
  { valor: '03', nome: 'Março' }, { valor: '04', nome: 'Abril' },
  { valor: '05', nome: 'Maio' }, { valor: '06', nome: 'Junho' },
  { valor: '07', nome: 'Julho' }, { valor: '08', nome: 'Agosto' },
  { valor: '09', nome: 'Setembro' }, { valor: '10', nome: 'Outubro' },
  { valor: '11', nome: 'Novembro' }, { valor: '12', nome: 'Dezembro' }
]
const diasNascimento = computed(() => {
  const mes = Number(nascimentoMes.value)
  const ano = Number(nascimentoAno.value)
  const totalDias = mes && ano ? new Date(ano, mes, 0).getDate() : 31
  return Array.from({ length: totalDias }, (_, index) => String(index + 1).padStart(2, '0'))
})

function atualizarDataNascimento() {
  if (nascimentoDia.value && nascimentoMes.value && nascimentoAno.value) {
    const ultimoDia = diasNascimento.value[diasNascimento.value.length - 1]
    if (Number(nascimentoDia.value) > Number(ultimoDia)) nascimentoDia.value = ultimoDia
    dataNascimento.value = `${nascimentoAno.value}-${nascimentoMes.value}-${nascimentoDia.value}`
    return
  }
  dataNascimento.value = ''
}
const loadingConsulta = ref(false)
const erroConsulta = ref('')

// Dados do Ingresso Ativo
const dadosUsuario = ref(null)
const dadosIngresso = ref(null)
const qrDataUrl = ref('')

// Dados da Validação Pendente / Rejeitada
const infoValidacao = ref(null)

// Fluxo de Cancelamento
const motivoCancelamento = ref('')
const loadingIniciarCancel = ref(false)
const tokenSessao = ref('')
const emailMascarado = ref('')
const codigoConfirmacao = ref('')
const loadingValidarCodigo = ref(false)
const erroCodigo = ref('')
const reenviandoCodigo = ref(false)
const cooldownReenvio = ref(0)
let timerCooldown = null

const fotoAoVivo = ref('')
const loadingEnviarFoto = ref(false)
const erroFoto = ref('')

const protocoloCancelamento = ref('')
const statusCancelamento = ref('pendente_analise')

// Formatação do CPF
function onCpfInput(e) {
  let val = e.target.value.replace(/\D/g, '').slice(0, 11)
  if (val.length > 9) {
    val = val.replace(/(\d{3})(\d{3})(\d{3})(\d{1,2})/, '$1.$2.$3-$4')
  } else if (val.length > 6) {
    val = val.replace(/(\d{3})(\d{3})(\d{1,3})/, '$1.$2.$3')
  } else if (val.length > 3) {
    val = val.replace(/(\d{3})(\d{1,3})/, '$1.$2')
  }
  cpf.value = val
  erroConsulta.value = ''
}

// Geração de QR Code Local
async function gerarQrCodeLocal(token) {
  if (!token) return
  try {
    qrDataUrl.value = await QRCode.toDataURL(token, {
      width: 280,
      margin: 2,
      color: {
        dark: '#0f172a',
        light: '#ffffff'
      }
    })
  } catch (err) {
    // Falha ao renderizar QR Code
  }
}

// 1. Consulta de Ingresso
async function handleConsultarIngresso() {
  erroConsulta.value = ''
  const cpfLimpo = cpf.value.replace(/\D/g, '')

  if (cpfLimpo.length !== 11) {
    erroConsulta.value = 'Por favor, digite um CPF válido com 11 dígitos.'
    return
  }

  if (!dataNascimento.value) {
    erroConsulta.value = 'A data de nascimento é obrigatória.'
    return
  }

  loadingConsulta.value = true
  try {
    const res = await fetch('/api/meu-ingresso/consultar', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        cpf: cpfLimpo,
        data_nascimento: dataNascimento.value,
        motivo: motivoCancelamento.value.trim() || 'Desist?ncia volunt?ria pelo servidor.'
      })
    })

    const data = await res.json()

    if (!res.ok) {
      erroConsulta.value = data.detail || 'Nenhum registro encontrado para os dados informados.'
      return
    }

    if (data.status === 'ingresso_ativo') {
      dadosUsuario.value = data.usuario
      dadosIngresso.value = data.ingresso
      await gerarQrCodeLocal(data.ingresso?.qr_code_token)
      etapaAtual.value = 'ticket'
    } else if (data.status === 'validacao_pendente') {
      infoValidacao.value = data
      etapaAtual.value = 'validacao_pendente'
    } else if (data.status === 'validacao_rejeitada') {
      infoValidacao.value = data
      etapaAtual.value = 'validacao_rejeitada'
    } else if (data.status === 'ingresso_cancelado') {
      infoValidacao.value = data
      etapaAtual.value = 'ingresso_cancelado'
    }
  } catch (err) {
    erroConsulta.value = 'Erro de comunicação com o servidor. Verifique sua conexão e tente novamente.'
  } finally {
    loadingConsulta.value = false
  }
}

function handleImprimir() {
  if (dadosIngresso.value?.qr_code_token) {
    window.open(`/api/meu-ingresso/download-pdf/${dadosIngresso.value.qr_code_token}`, '_blank')
  }
}

function resetarConsulta() {
  etapaAtual.value = 'consulta'
  dadosUsuario.value = null
  dadosIngresso.value = null
  infoValidacao.value = null
  qrDataUrl.value = ''
  erroConsulta.value = ''
}

// Inicia contagem regressiva para reenvio de código
function iniciarCooldown(segundos = 60) {
  cooldownReenvio.value = segundos
  if (timerCooldown) clearInterval(timerCooldown)
  timerCooldown = setInterval(() => {
    if (cooldownReenvio.value > 0) {
      cooldownReenvio.value -= 1
    } else {
      clearInterval(timerCooldown)
    }
  }, 1000)
}

// 2. Iniciar Fluxo de Cancelamento sob Demanda
async function handleIniciarCancelamento() {
  const cpfLimpo = cpf.value.replace(/\D/g, '')
  loadingIniciarCancel.value = true
  try {
    const res = await fetch('/api/meu-ingresso/iniciar', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        cpf: cpfLimpo,
        data_nascimento: dataNascimento.value
      })
    })

    const data = await res.json()

    if (!res.ok) {
      toast.error(data.detail || 'Não foi possível iniciar o cancelamento.')
      return
    }

    tokenSessao.value = data.token
    protocoloCancelamento.value = data.protocolo || ''

    if (data.ja_em_analise) {
      statusCancelamento.value = 'pendente_analise'
      etapaAtual.value = 'cancel_concluido'
      return
    }

    emailMascarado.value = data.email_mascarado || 'seu e-mail cadastrado'
    if (data.status === 'pendente_foto') {
      etapaAtual.value = 'cancel_selfie'
      return
    }
    codigoConfirmacao.value = ''
    erroCodigo.value = data.codigo_expirado
      ? 'O código anterior expirou. Clique em Reenviar código por e-mail para receber outro.'
      : ''
    etapaAtual.value = 'cancel_2fa'
    iniciarCooldown(data.reenviar_em_segundos ?? 60)
    if (data.retomado) {
      toast.info('Você retomou o cancelamento. Para receber outro código, use o botão Reenviar código por e-mail.')
    }
  } catch (err) {
    toast.error('Erro de conexão ao solicitar cancelamento.')
  } finally {
    loadingIniciarCancel.value = false
  }
}

// Validar Código 2FA
async function handleValidarCodigo() {
  erroCodigo.value = ''
  const cod = codigoConfirmacao.value.trim()

  if (cod.length !== 6) {
    erroCodigo.value = 'O código deve conter exatamente 6 dígitos numéricos.'
    return
  }

  loadingValidarCodigo.value = true
  try {
    const res = await fetch('/api/meu-ingresso/validar-codigo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        token: tokenSessao.value,
        codigo: cod
      })
    })

    const data = await res.json()

    if (!res.ok) {
      erroCodigo.value = data.detail || 'Código inválido ou expirado.'
      return
    }

    etapaAtual.value = 'cancel_selfie'
  } catch (err) {
    erroCodigo.value = 'Erro de comunicação ao validar código.'
  } finally {
    loadingValidarCodigo.value = false
  }
}

// Reenviar Código 2FA
async function handleReenviarCodigo() {
  if (cooldownReenvio.value > 0) return
  reenviandoCodigo.value = true
  erroCodigo.value = ''
  try {
    const res = await fetch('/api/meu-ingresso/reenviar-codigo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: tokenSessao.value })
    })
    const data = await res.json()
    if (!res.ok) {
      erroCodigo.value = data.detail || 'Não foi possível reenviar o código.'
      const espera = Number(res.headers.get('Retry-After') || 0)
      if (espera > 0) iniciarCooldown(espera)
      return
    }
    iniciarCooldown(60)
  } catch (err) {
    erroCodigo.value = 'Erro ao solicitar reenvio.'
  } finally {
    reenviandoCodigo.value = false
  }
}

// Concluir com Selfie ao Vivo
async function handleConcluirCancelamento() {
  erroFoto.value = ''
  if (!fotoAoVivo.value) {
    erroFoto.value = 'É obrigatório capturar sua foto facial ao vivo para concluir o cancelamento.'
    return
  }

  loadingEnviarFoto.value = true
  try {
    const res = await fetch('/api/meu-ingresso/concluir', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        token: tokenSessao.value,
        foto_base64: fotoAoVivo.value,
        motivo: motivoCancelamento.value.trim() || 'Desist?ncia volunt?ria pelo servidor.'
      })
    })

    const data = await res.json()

    if (!res.ok) {
      erroFoto.value = data.detail || 'Erro ao processar sua foto facial.'
      return
    }

    protocoloCancelamento.value = data.protocolo || ''
    statusCancelamento.value = data.status || 'pendente_analise'
    etapaAtual.value = 'cancel_concluido'
  } catch (err) {
    erroFoto.value = 'Erro de conexão ao enviar cancelamento.'
  } finally {
    loadingEnviarFoto.value = false
  }
}
</script>


<template>
  <div class="meu-ingresso-page public-query-page">
    <div class="app-container app-container-narrow public-query-container">

      <!-- ============================================================== -->
      <!-- ETAPA 1: CONSULTA DE INGRESSO (PADRÃO AO ACESSAR)               -->
      <!-- ============================================================== -->
      <div v-if="etapaAtual === 'consulta'" class="card-glass-main public-query-card">
        <div class="public-page-header public-query-header">
          <div class="badge-step-tag font-outfit public-query-badge"><i class="bi bi-ticket-perforated" aria-hidden="true"></i> CONSULTA OFICIAL</div>
          <h1 class="page-title-center font-quattrocento public-query-title">Meu Ingresso • Serv indoor</h1>
          <p class="page-desc-center public-query-description">
            Informe seu CPF e Data de Nascimento para visualizar seu ingresso digital com QR Code, imprimir sua 2ª via ou gerenciar sua participação.
          </p>
        </div>

        <div v-if="erroConsulta" class="alert-box-danger">
          <i class="bi bi-exclamation-triangle-fill alert-icon"></i>
          <span>{{ erroConsulta }}</span>
        </div>

        <form @submit.prevent="handleConsultarIngresso" class="form-grid public-query-form">
          <div class="form-group">
            <label class="form-label" for="input-cpf"><i class="bi bi-person-badge me-1 text-primary" aria-hidden="true"></i> CPF do Servidor:</label>
            <input
              id="input-cpf"
              v-model="cpf"
              type="tel"
              inputmode="numeric"
              maxlength="14"
              class="form-control-custom font-monospace"
              placeholder="000.000.000-00"
              required
              autocomplete="off"
              @input="onCpfInput"
            />
          </div>

          <div class="form-group">
            <label class="form-label" for="input-nascimento-dia"><i class="bi bi-calendar-event me-1 text-warning" aria-hidden="true"></i> Data de Nascimento:</label>
            <div class="date-select-grid">
              <div class="select-col col-dia">
                <select id="input-nascimento-dia" v-model="nascimentoDia" class="form-select date-select" required aria-label="Dia de nascimento" @change="atualizarDataNascimento">
                  <option value="" disabled>Dia</option>
                  <option v-for="dia in diasNascimento" :key="dia" :value="dia">{{ dia }}</option>
                </select>
              </div>
              <div class="select-col col-mes">
                <select id="input-nascimento-mes" v-model="nascimentoMes" class="form-select date-select" required aria-label="Mês de nascimento" @change="atualizarDataNascimento">
                  <option value="" disabled>Mês</option>
                  <option v-for="mes in mesesNascimento" :key="mes.valor" :value="mes.valor">{{ mes.nome }}</option>
                </select>
              </div>
              <div class="select-col col-ano">
                <select id="input-nascimento-ano" v-model="nascimentoAno" class="form-select date-select" required aria-label="Ano de nascimento" @change="atualizarDataNascimento">
                  <option value="" disabled>Ano</option>
                  <option v-for="ano in anosNascimento" :key="ano" :value="ano">{{ ano }}</option>
                </select>
              </div>
            </div>
          </div>

          <button
            type="submit"
            class="btn btn-primary w-100 font-outfit public-query-submit"
            :disabled="loadingConsulta"
          >
            <span v-if="!loadingConsulta"><i class="bi bi-search me-2"></i> Consultar Ingresso</span>
            <span v-else><i class="bi bi-hourglass-split me-2"></i> Consultando...</span>
          </button>
        </form>
      </div>

      <!-- ============================================================== -->
      <!-- ETAPA 2: EXIBIÇÃO DO INGRESSO DIGITAL ATIVO                     -->
      <!-- ============================================================== -->
      <div v-else-if="etapaAtual === 'ticket'" class="ticket-view-wrapper">
        
        <!-- CARTÃO DO INGRESSO OFICIAL (ÁREA IMPRIMÍVEL) -->
        <div id="area-ingresso-imprimivel" class="ticket-card-official">
          
          <!-- Cabeçalho do Ingresso -->
          <div class="ticket-top-banner">
            <div class="ticket-brand">
              <img src="/images/logo_servindoor_sem-fundo.png" alt="Serv indoor" class="ticket-logo-small" />
              <div>
                <span class="ticket-fest-name font-quattrocento quattrocento-bold">Serv indoor 2026</span>
                <span class="ticket-fest-sub">A Festa do Servidor Público</span>
              </div>
            </div>
            <div class="ticket-badge-official">
              <span class="badge-status-ticket" :class="dadosIngresso?.presente ? 'badge-presente' : 'badge-ativo'">
                <i :class="dadosIngresso?.presente ? 'bi bi-patch-check-fill' : 'bi bi-qr-code-scan'"></i>
                {{ dadosIngresso?.presente ? 'Presença Confirmada' : 'Entrada Liberada' }}
              </span>
            </div>
          </div>

          <!-- Divisória serrilhada estilo Ticket -->
          <div class="ticket-rip-line">
            <span class="rip-notch notch-left"></span>
            <span class="rip-dots"></span>
            <span class="rip-notch notch-right"></span>
          </div>

          <!-- Corpo do Ingresso -->
          <div class="ticket-main-body">
            
            <!-- Dados do Servidor -->
            <div class="ticket-info-block">
              <div class="ticket-row-main">
                <span class="ticket-label">Participante / Servidor</span>
                <strong class="ticket-value-name font-quattrocento quattrocento-bold">{{ dadosUsuario?.nome }}</strong>
              </div>

              <div class="ticket-details-grid">
                <div>
                  <span class="ticket-label">CPF</span>
                  <span class="ticket-value font-monospace">{{ dadosUsuario?.cpf_formatado }}</span>
                </div>
                <div>
                  <span class="ticket-label">Lote Resgatado</span>
                  <span class="ticket-value font-outfit text-cyan">{{ dadosIngresso?.lote_nome }}</span>
                </div>
                <div>
                  <span class="ticket-label">Secretaria / Órgão</span>
                  <span class="ticket-value">{{ dadosUsuario?.secretaria_nome }}</span>
                </div>
                <div>
                  <span class="ticket-label">Data de Resgate</span>
                  <span class="ticket-value">{{ dadosIngresso?.data_resgate }}</span>
                </div>
              </div>
            </div>

            <!-- QR Code de Acesso -->
            <div class="ticket-qr-block">
              <div class="qr-wrapper">
                <img v-if="qrDataUrl" :src="qrDataUrl" alt="QR Code Oficial" class="qr-code-img" />
                <div v-else class="qr-loading">
                  <div class="spinner-border text-primary"></div>
                </div>
              </div>
              <span class="qr-token font-monospace">{{ dadosIngresso?.qr_code_token }}</span>
              <span class="qr-hint">Apresente este QR Code na portaria oficial</span>
            </div>

          </div>

          <!-- Rodapé do Ingresso -->
          <div class="ticket-footer-legal">
            <span>Ingresso individual e intransferível. Obrigatória apresentação de documento oficial com foto.</span>
          </div>

        </div>

        <!-- BOTÕES DE AÇÃO DO INGRESSO (NÃO IMPRIMÍVEIS) -->
        <div class="ticket-actions-bar no-print">
          <a
            :href="'/api/meu-ingresso/download-pdf/' + dadosIngresso?.qr_code_token"
            target="_blank"
            class="btn btn-primary font-outfit btn-download-art"
          >
            <i class="bi bi-file-earmark-pdf-fill me-2"></i> Baixar Ingresso (PDF)
          </a>
          <a
            :href="'/api/meu-ingresso/download-imagem/' + dadosIngresso?.qr_code_token"
            target="_blank"
            download
            class="btn btn-secondary font-outfit"
          >
            <i class="bi bi-download me-2"></i> Baixar Imagem (PNG)
          </a>
          <button type="button" class="btn btn-secondary font-outfit" @click="resetarConsulta">
            <i class="bi bi-arrow-left me-2"></i> Nova Consulta
          </button>
        </div>

        <!-- SEÇÃO DISCRETA DE CANCELAMENTO SOB DEMANDA -->
        <div class="cancellation-demand-card no-print">
          <div class="cancellation-demand-content">
            <div class="cancellation-icon-wrap">
              <i class="bi bi-calendar-x text-danger"></i>
            </div>
            <div>
              <h3 class="cancellation-demand-title">Não poderá comparecer ao evento?</h3>
              <p class="cancellation-demand-desc">
                Caso não possa comparecer, você pode solicitar o cancelamento do ingresso. A ocupação do lote será mantida.
                <strong class="text-danger d-block mt-1">Atenção: Ao cancelar, seu CPF não poderá resgatar novo ingresso em outros lotes.</strong>
              </p>
              <div class="cancellation-reason-input mt-2 mb-3">
                <input
                  v-model="motivoCancelamento"
                  type="text"
                  class="form-control-custom w-100 small"
                  placeholder="Motivo da desistência (ex: imprevisto particular, plantão)..."
                />
              </div>
            </div>
          </div>
          <button
            type="button"
            class="btn-cancel-demand font-outfit"
            :disabled="loadingIniciarCancel"
            @click="handleIniciarCancelamento"
          >
            <span v-if="!loadingIniciarCancel"><i class="bi bi-shield-x me-1"></i> Solicitar Cancelamento</span>
            <span v-else>Iniciando...</span>
          </button>
        </div>

      </div>

      <!-- ============================================================== -->
      <!-- CASO: SOLICITAÇÃO DE VALIDAÇÃO PENDENTE                        -->
      <!-- ============================================================== -->
      <div v-else-if="etapaAtual === 'validacao_pendente'" class="card-glass-main text-center pending-analysis-card">
        <div class="status-icon-box bg-warning-subtle text-warning">
          <i class="bi bi-hourglass-split"></i>
        </div>
        <div class="badge-step-tag font-outfit">EM ANÁLISE CADASTRAL</div>
        <h2 class="step-title font-outfit">Solicitação Recebida com Sucesso!</h2>
        
        <p class="step-desc">
          Olá, <strong>{{ infoValidacao?.usuario?.nome }}</strong>. Seu cadastro foi recebido e está em processo de verificação cadastral pela comissão organizadora para confirmação de vínculo com a Prefeitura.
        </p>

        <div class="protocol-card my-3">
          <span class="protocol-label">Protocolo de Homologação</span>
          <span class="protocol-number font-outfit text-warning">{{ infoValidacao?.protocolo }}</span>
          <span class="protocol-badge badge-warning">Vaga Pré-Reservada no Lote</span>
        </div>

        <div class="explanation-box">
          <div class="explanation-title font-outfit">
            <i class="bi bi-info-circle-fill text-cyan me-2"></i> Próximos Passos:
          </div>
          <ul class="explanation-list">
            <li>Sua vaga está garantida durante a conferência cadastral.</li>
            <li>O prazo estimado para conclusão da análise é de <strong>até 3 dias úteis</strong>.</li>
            <li>Assim que aprovado, seu ingresso oficial com QR Code será enviado para seu e-mail e liberado nesta consulta.</li>
          </ul>
        </div>

        <button type="button" class="btn btn-secondary font-outfit" @click="resetarConsulta">
          <i class="bi bi-arrow-left me-2"></i> Voltar à Consulta
        </button>
      </div>

      <!-- ============================================================== -->
      <!-- CASO: SOLICITAÇÃO REJEITADA                                    -->
      <!-- ============================================================== -->
      <div v-else-if="etapaAtual === 'validacao_rejeitada'" class="card-glass-main text-center">
        <div class="status-icon-box bg-danger-subtle text-danger">
          <i class="bi bi-x-octagon-fill"></i>
        </div>
        <div class="badge-step-tag font-outfit">SOLICITAÇÃO INDEFERIDA</div>
        <h2 class="step-title font-outfit">Validação Não Aprovada</h2>
        
        <div class="alert-box-danger my-3">
          <i class="bi bi-exclamation-triangle-fill alert-icon"></i>
          <div>
            <strong>Motivo informado pela organização:</strong>
            <p class="mb-0 mt-1">{{ infoValidacao?.motivo }}</p>
          </div>
        </div>

        <p class="step-desc">
          Caso discorde da avaliação, procure a comissão organizadora do Serv indoor ou o setor de Recursos Humanos da sua Secretaria com documento comprobatório de vínculo.
        </p>

        <button type="button" class="btn btn-secondary font-outfit mt-3" @click="resetarConsulta">
          <i class="bi bi-arrow-left me-2"></i> Voltar à Consulta
        </button>
      </div>

      <!-- ============================================================== -->
      <!-- CASO: INGRESSO CANCELADO                                       -->
      <!-- ============================================================== -->
      <div v-else-if="etapaAtual === 'ingresso_cancelado'" class="card-glass-main text-center">
        <div class="status-icon-box bg-secondary text-white">
          <i class="bi bi-slash-circle-fill"></i>
        </div>
        <div class="badge-step-tag font-outfit">INGRESSO CANCELADO</div>
        <h2 class="step-title font-outfit">Ingresso Inativo</h2>
        <p class="step-desc">
          O ingresso emitido para este CPF foi cancelado anteriormente e continua contabilizado na ocupação do lote do evento.
        </p>

        <button type="button" class="btn btn-secondary font-outfit mt-3" @click="resetarConsulta">
          <i class="bi bi-arrow-left me-2"></i> Voltar à Consulta
        </button>
      </div>

      <!-- ============================================================== -->
      <!-- FLUXO CANCELAMENTO: ETAPA 2FA CÓDIGO EMAIL                     -->
      <!-- ============================================================== -->
      <div v-else-if="etapaAtual === 'cancel_2fa'" class="card-glass-main cancel-2fa-card">
        <div class="step-header cancel-2fa-header step-header--centered">
          <div class="badge-step-tag font-outfit">SEGURANÇA 2FA</div>
          <h2 class="step-title font-outfit">Confirmar Código de Segurança</h2>
          <p class="step-desc">
            Para continuar, digite o código de 6 dígitos recebido no e-mail:
            <strong class="text-white">{{ emailMascarado }}</strong>
          </p>
          <p class="step-desc cancel-code-validity">
            O código vale por 15 minutos. Se sair desta tela para consultar o e-mail, volte ao ingresso e solicite o cancelamento novamente para retomar esta etapa sem gerar outro envio.
          </p>
        </div>

        <div v-if="erroCodigo" class="alert-box-danger">
          <i class="bi bi-exclamation-triangle-fill alert-icon"></i>
          <span>{{ erroCodigo }}</span>
        </div>

        <form @submit.prevent="handleValidarCodigo" class="form-grid">
          <div class="form-group text-center">
            <input
              v-model="codigoConfirmacao"
              type="text"
              inputmode="numeric"
              maxlength="6"
              class="form-control-custom input-code-digits"
              placeholder="000000"
              required
              autofocus
            />
            <span class="hint-code">Digite os 6 dígitos numéricos recebidos por e-mail</span>
          </div>

          <button
            type="submit"
            class="btn btn-primary w-100 font-outfit"
            :disabled="loadingValidarCodigo"
          >
            <span v-if="!loadingValidarCodigo">Validar Código e Avançar</span>
            <span v-else>Verificando...</span>
          </button>
        </form>

        <div class="resend-box mt-3 text-center">
          <button
            type="button"
            class="btn-resend-link font-outfit"
            :disabled="cooldownReenvio > 0 || reenviandoCodigo"
            @click="handleReenviarCodigo"
          >
            <span v-if="cooldownReenvio > 0">Reenviar código em {{ cooldownReenvio }}s</span>
            <span v-else-if="reenviandoCodigo">Enviando novo código...</span>
            <span v-else>Não recebeu? Reenviar código por e-mail</span>
          </button>
        </div>

        <div class="back-link-box mt-3 text-center">
          <button type="button" class="btn-link-subtle" @click="etapaAtual = 'ticket'">
            <i class="bi bi-arrow-left me-1"></i> Voltar ao Meu Ingresso
          </button>
        </div>
      </div>

      <!-- ============================================================== -->
      <!-- FLUXO CANCELAMENTO: ETAPA SELFIE AO VIVO                       -->
      <!-- ============================================================== -->
      <div v-else-if="etapaAtual === 'cancel_selfie'" class="card-glass-main cancel-selfie-card">
        <div class="step-header cancel-selfie-header step-header--centered">
          <div class="badge-step-tag font-outfit">CONFERÊNCIA BIOMÉTRICA</div>
          <h2 class="step-title font-outfit">Confirmação Facial ao Vivo</h2>
          <p class="step-desc">
            Para sua segurança e prevenir cancelamentos indevidos por terceiros, capture uma selfie ao vivo para validação com a foto do seu ingresso.
          </p>
        </div>

        <div v-if="erroFoto" class="alert-box-danger">
          <i class="bi bi-exclamation-triangle-fill alert-icon"></i>
          <span>{{ erroFoto }}</span>
        </div>

        <div class="camera-wrapper">
          <WebcamCapture v-model="fotoAoVivo" />
        </div>

        <button
          type="button"
          class="btn btn-danger-critical btn-action-primary btn-cancel-confirm font-outfit mt-4 w-100 cancel-selfie-submit"
          :disabled="!fotoAoVivo || loadingEnviarFoto"
          @click="handleConcluirCancelamento"
        >
          <span v-if="!loadingEnviarFoto"><i class="bi bi-trash3-fill me-2"></i> Confirmar Cancelamento Definitivo</span>
          <span v-else><i class="bi bi-hourglass-split me-2"></i> Processando Cancelamento...</span>
        </button>

        <div class="back-link-box mt-3 text-center">
          <button type="button" class="btn-link-subtle" @click="etapaAtual = 'ticket'">
            <i class="bi bi-arrow-left me-1"></i> Desistir do Cancelamento
          </button>
        </div>
      </div>

      <!-- ============================================================== -->
      <!-- FLUXO CANCELAMENTO: ETAPA CONCLUÍDO                           -->
      <!-- ============================================================== -->
      <div v-else-if="etapaAtual === 'cancel_concluido'" class="card-glass-main text-center">
        <div class="status-icon-box bg-success-subtle text-emerald">
          <i class="bi bi-check-circle-fill"></i>
        </div>
        <div class="badge-step-tag font-outfit">SOLICITAÇÃO PROTOCOLADA</div>
        <h2 class="step-title font-outfit">Cancelamento Registrado!</h2>

        <div class="protocol-card my-3">
          <span class="protocol-label">Protocolo de Cancelamento</span>
          <span class="protocol-number font-outfit">{{ protocoloCancelamento }}</span>
          <span class="protocol-badge badge-warning">Aguardando Conferência Facial</span>
        </div>

        <div class="explanation-box">
          <div class="explanation-title font-outfit">
            <i class="bi bi-info-circle-fill text-cyan me-2"></i> O que acontece agora?
          </div>
          <ul class="explanation-list">
            <li>Sua solicitação e foto facial foram encaminhadas para conferência com a foto cadastrada no resgate.</li>
            <li>Após confirmação visual pelo administrador, seu ingresso será cancelado e continuará contabilizado na ocupação do lote.</li>
            <li>Você receberá a confirmação definitiva no seu e-mail cadastrado.</li>
          </ul>
        </div>

        <button type="button" class="btn btn-secondary font-outfit" @click="router.push('/')">
          <i class="bi bi-house-door me-2"></i> Voltar à Página Inicial
        </button>
      </div>

    </div>
  </div>
</template>

<style scoped>
@media (max-width: 520px) {
  .cancel-2fa-card .input-code-digits {
    width: 100%;
    max-width: 320px;
  }

  .cancel-selfie-card .camera-wrapper {
    width: 100%;
    min-width: 0;
  }

  .cancel-selfie-submit {
    width: 100%;
    white-space: normal;
    text-align: center;
  }
}

</style>
