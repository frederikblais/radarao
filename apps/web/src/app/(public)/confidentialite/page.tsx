import Link from "next/link";

import { t } from "@/lib/i18n";

export const metadata = { title: "Politique de confidentialité" };

/* Texte juridique : conservé ici sous forme de contenu (page statique), à faire réviser avant la mise en ligne publique. */
export default function Privacy() {
  return (
    <main id="contenu" className="mx-auto max-w-3xl space-y-4 px-4 py-10 text-sm leading-relaxed">
      <Link href="/" className="font-semibold text-brand">{t("app.name")}</Link>
      <h1 className="text-2xl font-semibold">{t("privacy.title")}</h1>
      <p>RadarAO est un projet personnel. Responsable de la protection des renseignements personnels : Frederik Blais (Loi 25).</p>
      <h2 className="text-lg font-semibold">Renseignements recueillis</h2>
      <p>Adresse courriel (connexion), profil d’entreprise (activités, régions, qualifications) et documents d’appel d’offres que vous téléversez. Ces documents peuvent contenir des renseignements personnels (noms, signatures, coordonnées).</p>
      <h2 className="text-lg font-semibold">Utilisation</h2>
      <p>Trier les avis du SEAO, analyser les dossiers que vous téléversez et produire la fiche, la liste de vérification et la recommandation. Les documents sont transmis à l’API Claude d’Anthropic pour l’analyse; le profil transmis pour le tri exclut le nom de l’entreprise, le NEQ et les coordonnées. Le lakehouse Databricks ne contient que des données ouvertes du SEAO, jamais vos documents ni votre profil.</p>
      <h2 className="text-lg font-semibold">Conservation et suppression</h2>
      <p>Les dossiers et leurs documents sont supprimés automatiquement 90 jours après leur création. Vous pouvez supprimer un dossier (base de données, stockage et copies chez Anthropic) ou votre compte en tout temps dans les paramètres.</p>
      <h2 className="text-lg font-semibold">Consentement</h2>
      <p>Un consentement explicite est demandé avant tout téléversement. L’application ne soumet jamais rien, ne contacte jamais un organisme public et ne s’inscrit nulle part en votre nom.</p>
      <h2 className="text-lg font-semibold">Hébergement</h2>
      <p>Hébergement en région canadienne lorsque possible.</p>
      <p className="text-muted">{t("common.attribution")}</p>
    </main>
  );
}
