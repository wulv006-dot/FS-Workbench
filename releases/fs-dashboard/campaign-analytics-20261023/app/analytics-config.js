/* Public configuration only. Personal API keys belong in the FS server environment. */
window.FC_ANALYTICS_CONFIG = {
  enabled: false,
  consentRequired: true,
  projectId: '682816',
  projectToken: 'phc_ovAnYz4K2JU2P6UEAaDreJsmE3htvvErPS34TTvDmbtw',
  apiHost: 'https://us.i.posthog.com',
  allowedHosts: ['www.mmoexp.com'],
  localPreviewJournal: true,
  registry: [
    {id:'fc27-weekly',view:'weekly',name:'每周好卡',path:'/Fc-27/Weekly-Scout.html',type:'commerce',status:'testing',version:'1',windowHours:24,matches:[]},
    {id:'fc27-sbc',view:'sbc',name:'SBC 核心搭档',path:'/Fc-27/Sbc-Companions.html',type:'commerce',status:'testing',version:'1',windowHours:24,matches:[]},
    {id:'fc27-trio',view:'trio',name:'Player Trio',path:'/Fc-27/Player-Trio.html',type:'commerce',status:'testing',version:'1',windowHours:24,matches:[]}
    ,{id:'fc27-matchday',view:'matchday',name:'Matchday 赛事竞猜（接入规划）',path:'/Fc-27/Matchday.html',type:'prediction',status:'draft',version:'1',windowHours:24,matches:[]}
  ]
};
