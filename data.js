/* ============================================
   FIXMATE SERVICES — CENTRAL DATA FILE
   Edit services, gallery, contact details and
   copy from this file only. No build step.
   ============================================ */

window.FM_DATA = {
  brand: {
    name: "FixMate Services",
    tagline: "Fixing Homes. Building Trust.",
    headline: "Property Maintenance & Multi-Trade Team",
    logo: "assets/img/logo-new.png",
    logoMark: "assets/img/logo-new.png",
    banner: "assets/brand/fixmate-banner-wide.jpg",
    site: "https://fixmateservices.co.uk"
  },

  contact: {
    phoneDisplay: "",
    phoneRaw: "+447784044111",
    whatsapp: "447784044111",
    email: "info@fixmateservices.co.uk",
    website: "fixmateservices.co.uk",
    area: "South & Central London"
  },

  /* Services are grouped visually. Every listed
     service appears exactly once. Add `icon` key
     (see ICONS in app.js) to override default. */
  serviceGroups: [
    {
      id: "maintenance",
      title: "Property Maintenance",
      summary: "General upkeep and repair work for homes and flats across the property.",
      items: [
        "Property Maintenance",
        "General Repairs & DIY",
        "Kitchen & Bathroom Maintenance",
        "Larger Property Maintenance Works"
      ]
    },
    {
      id: "carpentry",
      title: "Carpentry, Doors & Woodwork",
      summary: "Woodwork repairs, door fitting and adjustments carried out cleanly.",
      items: [
        "Carpentry & Woodwork",
        "Carpentry & Door Repairs",
        "Door Fitting & Adjustments"
      ]
    },
    {
      id: "locks",
      title: "Locks & Security",
      summary: "Lock fitting, replacement and general security-related hardware work.",
      items: [
        "Door Lock Installation & Replacement",
        "Locks & Security"
      ]
    },
    {
      id: "wet",
      title: "Plumbing, Tiling & Bathrooms",
      summary: "Basic plumbing, sink installation and tiling work for kitchens and bathrooms.",
      items: [
        "Basic Plumbing & Sink Installation",
        "Tiling & Bathroom Work"
      ]
    },
    {
      id: "electrical",
      title: "Electrical",
      summary: "Basic electrical and cable work carried out as part of maintenance jobs.",
      items: [
        "Basic Electrical & Cable Work"
      ]
    },
    {
      id: "painting",
      title: "Painting & Finishing",
      summary: "Painting, preparation and silicone sealing for a clean final finish.",
      items: [
        "Painting & Decorating",
        "Painting Preparation & Renovation Support",
        "Silicone Sealing & Finishing"
      ]
    },
    {
      id: "install",
      title: "Assembly & Installation",
      summary: "Furniture assembly and home fittings installed properly the first time.",
      items: [
        "Furniture Assembly",
        "Shelving & Cabinet Installation",
        "Cabinets & Shelves",
        "Curtain Pole Installation"
      ]
    },
    {
      id: "renovation",
      title: "Renovation Support",
      summary: "Practical support for renovation and refurbishment projects.",
      items: [
        "Renovation & Refurbishment Support"
      ]
    }
  ],

  /* Map each service name to an icon key in app.js ICONS */
  serviceIcons: {
    "Property Maintenance": "home",
    "General Repairs & DIY": "tools",
    "Kitchen & Bathroom Maintenance": "home",
    "Larger Property Maintenance Works": "home",
    "Carpentry & Woodwork": "saw",
    "Carpentry & Door Repairs": "saw",
    "Door Fitting & Adjustments": "door",
    "Door Lock Installation & Replacement": "lock",
    "Locks & Security": "shield",
    "Basic Plumbing & Sink Installation": "wrench",
    "Tiling & Bathroom Work": "tile",
    "Basic Electrical & Cable Work": "bolt",
    "Painting & Decorating": "roller",
    "Painting Preparation & Renovation Support": "roller",
    "Silicone Sealing & Finishing": "seal",
    "Furniture Assembly": "box",
    "Shelving & Cabinet Installation": "shelf",
    "Cabinets & Shelves": "shelf",
    "Curtain Pole Installation": "rod",
    "Renovation & Refurbishment Support": "ruler"
  },

  /* Short per-service descriptions used in the cards */
  serviceDescriptions: {
    "Property Maintenance": "Ongoing repairs and upkeep for residential properties.",
    "General Repairs & DIY": "Small household repairs and general DIY jobs.",
    "Kitchen & Bathroom Maintenance": "Routine maintenance in kitchens and bathrooms.",
    "Larger Property Maintenance Works": "Bigger maintenance jobs handled from start to finish.",
    "Carpentry & Woodwork": "Woodwork repairs, fixings and made-to-fit adjustments.",
    "Carpentry & Door Repairs": "Repairing damaged doors and timber frames.",
    "Door Fitting & Adjustments": "Hanging doors and easing hinges so they close properly.",
    "Door Lock Installation & Replacement": "Fitting new locks and replacing old ones.",
    "Locks & Security": "Security hardware fitted to keep the property secure.",
    "Basic Plumbing & Sink Installation": "Sink fitting and basic plumbing maintenance.",
    "Tiling & Bathroom Work": "Tiling and general bathroom repairs.",
    "Basic Electrical & Cable Work": "Basic electrical and cable work for maintenance jobs.",
    "Painting & Decorating": "Painting and decorating with tidy preparation.",
    "Painting Preparation & Renovation Support": "Preparing surfaces ready for painting.",
    "Silicone Sealing & Finishing": "Neat silicone sealing for kitchens and bathrooms.",
    "Furniture Assembly": "Flat-pack and assembled furniture built correctly.",
    "Shelving & Cabinet Installation": "Shelving and cabinets installed level and secure.",
    "Cabinets & Shelves": "Cabinet and shelf fitting throughout the home.",
    "Curtain Pole Installation": "Curtain poles measured, levelled and fitted.",
    "Renovation & Refurbishment Support": "Handyman support for renovation projects."
  },

  whyUs: [
    {
      title: "Reliable & Trusted Service",
      text: "Straightforward, dependable work from someone who turns up when they say they will."
    },
    {
      title: "Quality Workmanship",
      text: "Careful, tidy jobs built to last rather than quick temporary fixes."
    },
    {
      title: "Punctual & Efficient",
      text: "Respectful of your time, with jobs completed efficiently and left clean."
    },
    {
      title: "Professional Tools & Equipment",
      text: "The right tools and equipment for the job, brought to every visit."
    },
    {
      title: "Attention to Detail",
      text: "Finishing matters. The small details are the difference in the final result."
    },
    {
      title: "Customer Satisfaction",
      text: "Happy customers are the goal, from a single repair to ongoing maintenance."
    },
    {
      title: "Friendly & Professional Service",
      text: "Clear communication and a professional manner from first message to finish."
    }
  ],

  /* Gallery / Our Work projects.

     Each project has ONE primary image — a real before/after
     composite supplied by the client. `extra` holds further
     photos that belong to the same job and are rendered inside
     that same project, so no image is ever repeated across
     projects.

     Titles and summaries are real text elements in the markup,
     not baked into the images, so they stay readable and
     selectable on small screens.

     intrinsic width/height are declared to prevent layout shift;
     aspect ratio is never stretched by CSS. */
  projects: [
    {
      id: "staircase",
      title: "Staircase Renovation",
      summary: "Preparation, repairs and a clean painting finish to an internal staircase.",
      compare: {
        src: "assets/work/staircase-renovation.jpg",
        width: 1122,
        height: 1402,
        alt: "Before and after comparison of a staircase renovated by FixMate Services, showing the prepared and repaired staircase next to the finished painted result"
      }
    },
    {
      id: "ceiling",
      title: "Ceiling Repair & Repaint",
      summary: "A damaged ceiling surface repaired and repainted for a clean, bright finish.",
      compare: {
        src: "assets/work/ceiling-repair-repaint.jpg",
        width: 1122,
        height: 1402,
        alt: "Before and after comparison of a ceiling repair and repaint by FixMate Services, showing the damaged surface next to the freshly repainted ceiling"
      }
    },
    {
      id: "shed",
      title: "Shed Installation",
      summary: "Shed assembly and installation, adding practical storage to the property.",
      compare: {
        src: "assets/work/shed-installation.jpg",
        width: 1122,
        height: 1402,
        alt: "Before and after comparison of a shed installed by FixMate Services, showing the empty space next to the assembled shed"
      }
    },
    {
      id: "shopfront",
      title: "Shopfront Painting",
      summary: "Shopfront painting for the PARISSI business, shown before, during and after the work.",
      compare: {
        src: "assets/work/shopfront-painting-compare.jpg",
        width: 1122,
        height: 1402,
        alt: "Before and after comparison of shopfront painting carried out by FixMate Services on the PARISSI shopfront, showing the original paintwork, the work in progress and the repainted result"
      },
      extra: [
        {
          src: "assets/work/shopfront-painting-01.jpg",
          width: 1100,
          height: 1600,
          alt: "Photograph of the repainted PARISSI shopfront exterior",
          caption: "Shopfront exterior"
        },
        {
          src: "assets/work/shopfront-painting-02.jpg",
          width: 1200,
          height: 1600,
          alt: "Second photograph of the repainted PARISSI shopfront exterior",
          caption: "Shopfront exterior, second view"
        }
      ]
    }
  ],

  formServices: [
    "Property Maintenance",
    "Carpentry & Woodwork",
    "Carpentry & Door Repairs",
    "Door Fitting & Adjustments",
    "Door Lock Installation & Replacement",
    "Locks & Security",
    "Tiling & Bathroom Work",
    "Basic Plumbing & Sink Installation",
    "Basic Electrical & Cable Work",
    "Painting & Decorating",
    "Painting Preparation & Renovation Support",
    "Furniture Assembly",
    "Shelving & Cabinet Installation",
    "Curtain Pole Installation",
    "Silicone Sealing & Finishing",
    "General Repairs & DIY",
    "Kitchen & Bathroom Maintenance",
    "Cabinets & Shelves",
    "Renovation & Refurbishment Support",
    "Larger Property Maintenance Works"
  ]
};
